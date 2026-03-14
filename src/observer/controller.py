import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ..config import Config
from ..utils.logger import get_logger


class SnapshotValidationError(ValueError):
    pass


@dataclass
class ObserverStatusEvent:
    scope: str
    observer_id: str
    status: str
    detail: str = ""


@dataclass
class ObserverZoneDecision:
    scope: str
    observer_id: str = ""
    sequence: int = 0
    stale: bool = False
    extended_stale: bool = False
    mass_freeze_active: bool = False
    shadow_mode: bool = True
    desired_drained_ips: Set[str] = field(default_factory=set)
    effective_drained_ips: Set[str] = field(default_factory=set)
    blocked_ips: Set[str] = field(default_factory=set)
    dns_eligible_ips: Set[str] = field(default_factory=set)
    reasons_by_ip: Dict[str, List[str]] = field(default_factory=dict)
    force_active_effective_ips: Set[str] = field(default_factory=set)
    force_drained_effective_ips: Set[str] = field(default_factory=set)


class ObserverController:
    def __init__(self, config: Config):
        self.config = config
        self.logger = get_logger(__name__)
        self.enabled = config.observer_enabled
        self.shadow_mode = config.observer_shadow_mode
        self.shared_secret = config.observer_shared_secret.encode("utf-8")
        self.allowed_observer_ids = set(config.observer_allowed_ids)
        self.freshness_ttl_seconds = max(30, config.observer_freshness_ttl_seconds)
        self.extended_stale_threshold_seconds = max(
            self.freshness_ttl_seconds, config.observer_extended_stale_threshold_seconds
        )
        self.mass_degradation_threshold_ratio = min(1.0, max(0.0, config.observer_mass_degradation_threshold_ratio))
        self.force_active_ips = set(config.observer_force_active_ips)
        self.force_drained_ips = set(config.observer_force_drained_ips)
        self.state_file = Path(config.observer_state_file)
        self._pending_events: List[ObserverStatusEvent] = []
        self._runtime_status: Dict[str, Dict[str, object]] = {}
        self._state = self._load_state()
        self.refresh_runtime_status(notify=False)
        for scope, payload in self._state.get("scopes", {}).items():
            status = self._runtime_status.get(scope, {})
            if status.get("stale"):
                self._pending_events.append(
                    ObserverStatusEvent(
                        scope=scope,
                        observer_id=str(payload.get("observer_id", "")),
                        status="stale",
                        detail="restored from persisted state",
                    )
                )

    def _default_state(self) -> dict:
        return {"version": 1, "scopes": {}}

    def _load_state(self) -> dict:
        try:
            with self.state_file.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return self._default_state()
        except Exception as exc:
            self.logger.warning("Failed to load observer state from %s: %s", self.state_file, exc)
            return self._default_state()

        scopes = {}
        for scope, payload in (data.get("scopes") or {}).items():
            scopes[scope] = self._normalize_scope_state(scope, payload)
        return {"version": 1, "scopes": scopes}

    def _save_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_file.with_suffix(f"{self.state_file.suffix}.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(self._state, handle, indent=2, sort_keys=True)
        tmp_path.replace(self.state_file)

    def _normalize_scope_state(self, scope: str, payload: dict) -> dict:
        inventory = {}
        for ip, node in (payload.get("inventory") or {}).items():
            if not isinstance(node, dict):
                continue
            inventory[ip] = {
                "node": node.get("node", ip),
                "desired_state": "drained" if node.get("desired_state") == "drained" else "healthy",
                "restore_candidate": bool(node.get("restore_candidate")),
                "reasons": sorted(set(node.get("reasons") or [])),
            }

        applied_order = {}
        for ip, value in (payload.get("applied_order") or {}).items():
            try:
                applied_order[ip] = int(value)
            except (TypeError, ValueError):
                continue

        return {
            "observer_id": str(payload.get("observer_id", "")),
            "observer_scope": scope,
            "sequence": int(payload.get("sequence", 0)),
            "issued_at": int(payload.get("issued_at", 0)),
            "expires_at": int(payload.get("expires_at", 0)),
            "accepted_at": int(payload.get("accepted_at", 0)),
            "inventory": inventory,
            "raw_drained_ips": sorted(set(payload.get("raw_drained_ips") or [])),
            "applied_drained_ips": sorted(set(payload.get("applied_drained_ips") or [])),
            "applied_order": applied_order,
            "mass_freeze_active": bool(payload.get("mass_freeze_active", False)),
            "mass_freeze_new_candidates": int(payload.get("mass_freeze_new_candidates", 0)),
        }

    def _scope_status(self, payload: dict, now: Optional[int] = None) -> dict:
        now = int(now or time.time())
        accepted_at = int(payload.get("accepted_at", 0))
        expires_at = int(payload.get("expires_at", 0))
        fresh_until = min(expires_at, accepted_at + self.freshness_ttl_seconds) if accepted_at and expires_at else 0
        stale = bool(fresh_until and now > fresh_until)
        stale_for = max(0, now - fresh_until) if stale else 0
        return {
            "fresh_until": fresh_until,
            "stale": stale,
            "stale_for": stale_for,
            "extended_stale": stale and stale_for >= self.extended_stale_threshold_seconds,
            "mass_freeze_active": bool(payload.get("mass_freeze_active", False)),
        }

    def refresh_runtime_status(self, notify: bool = True, now: Optional[int] = None) -> None:
        now = int(now or time.time())
        scopes = self._state.get("scopes", {})
        for scope, payload in scopes.items():
            current = self._scope_status(payload, now=now)
            previous = self._runtime_status.get(scope)

            if notify and previous:
                observer_id = str(payload.get("observer_id", ""))
                if not previous.get("stale") and current["stale"]:
                    self._pending_events.append(
                        ObserverStatusEvent(
                            scope=scope,
                            observer_id=observer_id,
                            status="stale",
                            detail=f"freshness expired {current['stale_for']}s ago",
                        )
                    )
                if previous.get("stale") and not current["stale"]:
                    self._pending_events.append(
                        ObserverStatusEvent(scope=scope, observer_id=observer_id, status="recovered")
                    )
                if not previous.get("extended_stale") and current["extended_stale"]:
                    self._pending_events.append(
                        ObserverStatusEvent(
                            scope=scope,
                            observer_id=observer_id,
                            status="extended_stale",
                            detail=f"observer stale for {current['stale_for']}s",
                        )
                    )

            self._runtime_status[scope] = current

    def pop_events(self) -> List[ObserverStatusEvent]:
        self.refresh_runtime_status()
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def _scope_payload(self, scope: str) -> Optional[dict]:
        return self._state.get("scopes", {}).get(scope)

    def _verify_signature(self, body: bytes, signature: str) -> bool:
        if not self.shared_secret:
            raise SnapshotValidationError("observer shared secret is not configured")
        expected = hmac.new(self.shared_secret, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature or "")

    def _parse_nodes(self, nodes: list) -> Dict[str, dict]:
        inventory: Dict[str, dict] = {}
        for raw_node in nodes:
            if not isinstance(raw_node, dict):
                continue
            ip = str(raw_node.get("ip", "")).strip()
            if not ip:
                continue
            reasons = sorted(set(str(reason) for reason in (raw_node.get("reasons") or [])))
            inventory[ip] = {
                "node": str(raw_node.get("node", ip)).strip() or ip,
                "desired_state": "drained" if raw_node.get("desired_state") == "drained" else "healthy",
                "restore_candidate": bool(raw_node.get("restore_candidate", False)),
                "reasons": reasons,
            }
        return inventory

    def accept_snapshot(self, body: bytes, signature: str) -> dict:
        if not self.enabled:
            raise SnapshotValidationError("observer ingestion is disabled")
        if not self._verify_signature(body, signature):
            raise SnapshotValidationError("signature verification failed")

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SnapshotValidationError(f"invalid JSON payload: {exc}") from exc

        scope = str(payload.get("observer_scope", "")).strip()
        observer_id = str(payload.get("observer_id", "")).strip()
        if not scope:
            raise SnapshotValidationError("observer_scope is required")
        if not observer_id:
            raise SnapshotValidationError("observer_id is required")
        if self.allowed_observer_ids and observer_id not in self.allowed_observer_ids:
            raise SnapshotValidationError(f"observer_id {observer_id!r} is not allowed")

        try:
            sequence = int(payload.get("sequence", 0))
            issued_at = int(payload.get("issued_at", 0))
            expires_at = int(payload.get("expires_at", 0))
        except (TypeError, ValueError) as exc:
            raise SnapshotValidationError("sequence, issued_at, and expires_at must be integers") from exc

        if sequence <= 0:
            raise SnapshotValidationError("sequence must be positive")
        if issued_at <= 0 or expires_at <= 0:
            raise SnapshotValidationError("issued_at and expires_at must be positive")

        now = int(time.time())
        if expires_at <= now:
            raise SnapshotValidationError("snapshot has already expired")

        scope_payload = self._scope_payload(scope)
        if scope_payload:
            previous_observer_id = str(scope_payload.get("observer_id", ""))
            if previous_observer_id and previous_observer_id != observer_id:
                raise SnapshotValidationError(
                    f"scope {scope!r} already belongs to observer {previous_observer_id!r}"
                )
            if sequence <= int(scope_payload.get("sequence", 0)):
                raise SnapshotValidationError("snapshot sequence is not newer than the last accepted snapshot")

        inventory = self._parse_nodes(payload.get("nodes") or [])
        raw_drained_ips = {ip for ip, node in inventory.items() if node["desired_state"] == "drained"}

        previous = scope_payload or {}
        previous_status = self._scope_status(previous, now=now) if previous else {
            "stale": False,
            "extended_stale": False,
            "mass_freeze_active": False,
        }

        previous_applied = set(previous.get("applied_drained_ips") or [])
        previous_applied_order = dict(previous.get("applied_order") or {})
        new_candidates = raw_drained_ips - previous_applied
        inventory_size = len(inventory)
        mass_freeze_active = bool(
            inventory_size
            and new_candidates
            and (len(new_candidates) / inventory_size) > self.mass_degradation_threshold_ratio
        )

        if mass_freeze_active:
            applied_drained_ips = previous_applied & raw_drained_ips
            applied_order = {ip: previous_applied_order.get(ip, sequence) for ip in applied_drained_ips}
        else:
            applied_drained_ips = set(raw_drained_ips)
            applied_order = {ip: previous_applied_order.get(ip, sequence) for ip in applied_drained_ips}

        normalized_payload = {
            "observer_id": observer_id,
            "observer_scope": scope,
            "sequence": sequence,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "accepted_at": now,
            "inventory": inventory,
            "raw_drained_ips": sorted(raw_drained_ips),
            "applied_drained_ips": sorted(applied_drained_ips),
            "applied_order": applied_order,
            "mass_freeze_active": mass_freeze_active,
            "mass_freeze_new_candidates": len(new_candidates),
        }
        self._state.setdefault("scopes", {})[scope] = normalized_payload
        self._save_state()

        current_status = self._scope_status(normalized_payload, now=now)
        self._runtime_status[scope] = current_status

        if previous_status.get("stale"):
            self._pending_events.append(
                ObserverStatusEvent(scope=scope, observer_id=observer_id, status="recovered")
            )
        if previous_status.get("mass_freeze_active") != mass_freeze_active:
            self._pending_events.append(
                ObserverStatusEvent(
                    scope=scope,
                    observer_id=observer_id,
                    status="mass_freeze" if mass_freeze_active else "mass_freeze_cleared",
                    detail=(
                        f"blocked {len(new_candidates)} new drains across {inventory_size} observed IPs"
                        if mass_freeze_active
                        else ""
                    ),
                )
            )

        self.logger.info(
            "Accepted observer snapshot scope=%s observer=%s sequence=%s inventory=%s raw_drained=%s applied=%s"
            % (scope, observer_id, sequence, inventory_size, len(raw_drained_ips), len(applied_drained_ips))
        )
        return {
            "scope": scope,
            "observer_id": observer_id,
            "sequence": sequence,
            "inventory_count": inventory_size,
            "drained_count": len(raw_drained_ips),
            "applied_drained_count": len(applied_drained_ips),
            "mass_freeze_active": mass_freeze_active,
        }

    def handle_snapshot(self, body: bytes, signature: str) -> Tuple[int, dict]:
        try:
            result = self.accept_snapshot(body=body, signature=signature)
            return 202, {"ok": True, **result}
        except SnapshotValidationError as exc:
            self.logger.warning("Rejected observer snapshot: %s", exc)
            return 400, {"ok": False, "error": str(exc)}
        except Exception as exc:
            self.logger.error("Unhandled observer snapshot error: %s", exc, exc_info=True)
            return 500, {"ok": False, "error": "internal observer ingestion error"}

    def build_status_payload(self) -> dict:
        self.refresh_runtime_status()
        scopes = {}
        now = int(time.time())
        for scope, payload in self._state.get("scopes", {}).items():
            status = self._runtime_status.get(scope) or self._scope_status(payload, now=now)
            nodes = []
            applied_drained = set(payload.get("applied_drained_ips") or [])
            raw_drained = set(payload.get("raw_drained_ips") or [])
            for ip, node in sorted((payload.get("inventory") or {}).items()):
                nodes.append(
                    {
                        "ip": ip,
                        "node": node.get("node", ip),
                        "desired_state": node.get("desired_state", "healthy"),
                        "applied_state": "drained" if ip in applied_drained else "healthy",
                        "raw_state": "drained" if ip in raw_drained else "healthy",
                        "restore_candidate": bool(node.get("restore_candidate")),
                        "reasons": node.get("reasons", []),
                        "force_active": ip in self.force_active_ips,
                        "force_drained": ip in self.force_drained_ips,
                    }
                )
            scopes[scope] = {
                "observer_id": payload.get("observer_id", ""),
                "sequence": payload.get("sequence", 0),
                "issued_at": payload.get("issued_at", 0),
                "accepted_at": payload.get("accepted_at", 0),
                "expires_at": payload.get("expires_at", 0),
                "fresh_until": status.get("fresh_until", 0),
                "stale": status.get("stale", False),
                "extended_stale": status.get("extended_stale", False),
                "stale_for": status.get("stale_for", 0),
                "mass_freeze_active": payload.get("mass_freeze_active", False),
                "mass_freeze_new_candidates": payload.get("mass_freeze_new_candidates", 0),
                "inventory_count": len(nodes),
                "raw_drained_count": len(raw_drained),
                "applied_drained_count": len(applied_drained),
                "age_seconds": max(0, now - int(payload.get("accepted_at", now))),
                "nodes": nodes,
            }
        return {
            "ok": True,
            "enabled": self.enabled,
            "shadow_mode": self.shadow_mode,
            "freshness_ttl_seconds": self.freshness_ttl_seconds,
            "extended_stale_threshold_seconds": self.extended_stale_threshold_seconds,
            "mass_degradation_threshold_ratio": self.mass_degradation_threshold_ratio,
            "force_active_ips": sorted(self.force_active_ips),
            "force_drained_ips": sorted(self.force_drained_ips),
            "scopes": scopes,
        }

    def health_payload(self) -> dict:
        status = self.build_status_payload()
        stale_scopes = [scope for scope, payload in status["scopes"].items() if payload.get("stale")]
        return {
            "ok": True,
            "enabled": status["enabled"],
            "shadow_mode": status["shadow_mode"],
            "scope_count": len(status["scopes"]),
            "stale_scopes": stale_scopes,
        }

    def evaluate_zone(
        self,
        observer_scope: Optional[str],
        configured_ips: List[str],
        base_eligible_ips: Set[str],
        min_active_nodes: int,
    ) -> ObserverZoneDecision:
        configured_set = set(configured_ips)
        base_zone_eligible = {ip for ip in configured_set if ip in base_eligible_ips}
        decision = ObserverZoneDecision(
            scope=observer_scope or "",
            shadow_mode=self.shadow_mode,
            dns_eligible_ips=set(base_zone_eligible),
        )

        if not self.enabled or not observer_scope:
            return decision

        self.refresh_runtime_status()
        payload = self._scope_payload(observer_scope) or {}
        runtime_status = self._runtime_status.get(observer_scope, {})

        decision.observer_id = str(payload.get("observer_id", ""))
        decision.sequence = int(payload.get("sequence", 0))
        decision.stale = bool(runtime_status.get("stale", False))
        decision.extended_stale = bool(runtime_status.get("extended_stale", False))
        decision.mass_freeze_active = bool(payload.get("mass_freeze_active", False))

        inventory = payload.get("inventory") or {}
        base_desired = set(payload.get("applied_drained_ips") or []) & configured_set
        force_drained = self.force_drained_ips & configured_set
        force_active = self.force_active_ips & configured_set

        decision.force_drained_effective_ips = force_drained - base_desired
        decision.force_active_effective_ips = force_active & (base_desired | force_drained)
        decision.desired_drained_ips = (base_desired | force_drained) - force_active

        for ip in configured_set:
            reasons = list((inventory.get(ip) or {}).get("reasons", []))
            if ip in decision.force_drained_effective_ips:
                reasons.append("operator_force_drained")
            if ip in decision.force_active_effective_ips:
                reasons.append("operator_force_active")
            if reasons:
                decision.reasons_by_ip[ip] = sorted(set(reasons))

        applied_order = dict(payload.get("applied_order") or {})
        ordered_drains = sorted(
            [ip for ip in decision.desired_drained_ips if ip in base_zone_eligible],
            key=lambda ip: (
                0 if ip in force_drained else 1,
                applied_order.get(ip, 10**12),
                ip,
            ),
        )

        eligible = set(base_zone_eligible)
        for ip in ordered_drains:
            if ip not in eligible:
                continue
            if len(eligible) - 1 < max(0, min_active_nodes):
                decision.blocked_ips.add(ip)
                reasons = decision.reasons_by_ip.setdefault(ip, [])
                reasons.append("min_active_blocked")
                decision.reasons_by_ip[ip] = sorted(set(reasons))
                continue
            eligible.remove(ip)
            decision.effective_drained_ips.add(ip)

        decision.dns_eligible_ips = set(base_zone_eligible if self.shadow_mode else eligible)
        return decision
