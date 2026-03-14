from pathlib import Path
from typing import Optional

from fluent.runtime import FluentLocalization, FluentResourceLoader

from .events import (
    CapacityChange,
    CriticalState,
    DNSChange,
    DNSError,
    HealthCheckError,
    NodeStateChange,
    NodeStats,
    ObserverDecisionChange,
    ObserverStatusChange,
)
from ..utils.logger import get_logger


class MessageFormatter:
    SUPPORTED_LOCALES = ["en", "ru"]
    DEFAULT_LOCALE = "en"

    def __init__(self, locale: str = "en", locales_dir: Optional[Path] = None):
        self.logger = get_logger(__name__)
        self.locale = locale if locale in self.SUPPORTED_LOCALES else self.DEFAULT_LOCALE

        if locales_dir is None:
            locales_dir = Path(__file__).parent.parent / "locales"

        self.locales_dir = locales_dir
        self._loader = FluentResourceLoader(str(locales_dir / "{locale}"))
        self._l10n = FluentLocalization(
            locales=[self.locale, self.DEFAULT_LOCALE],
            resource_ids=["messages.ftl"],
            resource_loader=self._loader,
        )

    def format_node_state_change(self, change: NodeStateChange) -> str:
        stats = change.stats or NodeStats(total=0, online=0, disabled=0)

        if change.current_healthy:
            return self._l10n.format_value(
                "node-became-healthy",
                {
                    "name": change.node_name,
                    "address": change.node_address,
                    "total": stats.total,
                    "online": stats.online,
                    "disabled": stats.disabled,
                },
            )
        else:
            return self._l10n.format_value(
                "node-became-unhealthy",
                {
                    "name": change.node_name,
                    "address": change.node_address,
                    "reason": change.reason or "unknown",
                    "total": stats.total,
                    "online": stats.online,
                    "disabled": stats.disabled,
                },
            )

    def format_dns_change(self, change: DNSChange) -> str:
        msg_id = "dns-record-added" if change.action == "added" else "dns-record-removed"
        return self._l10n.format_value(
            msg_id, {"domain": f"{change.zone_name}.{change.domain}", "ip": change.ip_address}
        )

    def format_dns_error(self, error: DNSError) -> str:
        return self._l10n.format_value(
            "dns-operation-error",
            {
                "domain": f"{error.zone_name}.{error.domain}",
                "ip": error.ip_address,
                "action": error.action,
                "error": error.error_message,
            },
        )

    def format_critical_state(self, state: CriticalState) -> str:
        return self._l10n.format_value(
            "all-nodes-down", {"total": state.total_nodes, "nodes": ", ".join(state.down_nodes)}
        )

    def format_health_check_error(self, error: HealthCheckError) -> str:
        return self._l10n.format_value("health-check-error", {"error": error.error_message})

    def format_service_started(self) -> str:
        return self._l10n.format_value("service-started")

    def format_service_stopped(self) -> str:
        return self._l10n.format_value("service-stopped")

    def format_capacity_change(self, change: CapacityChange) -> str:
        msg_id = "node-throttled" if change.action == "throttled" else "node-restored"
        return self._l10n.format_value(
            msg_id,
            {
                "name": change.node_name,
                "address": change.node_address,
                "users": change.users_online,
                "threshold": change.threshold,
                "domain": f"{change.zone_name}.{change.domain}",
            },
        )

    def format_observer_status_change(self, change: ObserverStatusChange) -> str:
        message_id = {
            "stale": "observer-stale",
            "recovered": "observer-recovered",
            "extended_stale": "observer-extended-stale",
            "mass_freeze": "observer-mass-freeze",
            "mass_freeze_cleared": "observer-mass-freeze-cleared",
        }.get(change.status, "observer-stale")
        return self._l10n.format_value(
            message_id,
            {
                "scope": change.scope,
                "observer": change.observer_id,
                "detail": change.detail or "n/a",
            },
        )

    def format_observer_decision_change(self, change: ObserverDecisionChange) -> str:
        message_id = {
            "drained": "observer-drained",
            "restored": "observer-restored",
            "blocked": "observer-blocked",
            "shadow_drained": "observer-shadow-drained",
            "shadow_restored": "observer-shadow-restored",
            "force_active": "observer-force-active",
            "force_drained": "observer-force-drained",
        }.get(change.action, "observer-drained")
        return self._l10n.format_value(
            message_id,
            {
                "scope": change.scope,
                "name": change.node_name,
                "address": change.ip_address,
                "domain": f"{change.zone_name}.{change.domain}",
                "reasons": ", ".join(change.reasons) if change.reasons else "n/a",
                "detail": change.detail or "n/a",
            },
        )
