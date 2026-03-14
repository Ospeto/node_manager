from typing import TYPE_CHECKING, Dict, List, Optional, Set

from .cloudflare_dns import CloudflareClient, DNSManager
from .config import Config
from .observer import ObserverController, ObserverStatusEvent, ObserverZoneDecision
from .remnawave import NodeMonitor
from .utils.logger import get_logger

if TYPE_CHECKING:
    from .telegram import TelegramNotifier


class MonitoringService:
    def __init__(
        self,
        config: Config,
        node_monitor: NodeMonitor,
        cloudflare_client: CloudflareClient,
        dns_manager: DNSManager,
        notifier: Optional["TelegramNotifier"] = None,
        observer_controller: Optional[ObserverController] = None,
    ):
        self.config = config
        self.node_monitor = node_monitor
        self.cloudflare_client = cloudflare_client
        self.dns_manager = dns_manager
        self.notifier = notifier
        self.observer_controller = observer_controller
        self.logger = get_logger(__name__)
        self._zone_id_cache: Dict[str, str] = {}
        self._previous_node_states: Dict[str, bool] = {}
        self._previous_all_down: bool = False
        self._overloaded_ips: Set[str] = set()
        self._observer_zone_state: Dict[str, Dict[str, Set[str] | bool]] = {}

    async def initialize_and_print_zones(self) -> None:
        self.logger.info("Initializing zones")

        current_domain = None
        for zone in self.config.get_all_zones():
            domain = zone["domain"]

            if domain != current_domain:
                zone_id = await self._get_zone_id(domain)
                if not zone_id:
                    self.logger.warning("Could not find zone_id for domain %s", domain)
                    continue
                self.logger.info("Domain: %s, Zone ID: %s", domain, zone_id)
                current_domain = domain

            full_domain = f"{zone['name']}.{domain}"
            self.logger.info(
                "  Zone: %s, TTL: %s, Proxied: %s, Observer scope: %s",
                full_domain,
                zone["ttl"],
                zone["proxied"],
                zone.get("observer_scope") or "disabled",
            )

            self.logger.info("  Configured IPs: %s", ", ".join(zone["ips"]))

            zone_id = await self._get_zone_id(domain)
            existing_records = await self.cloudflare_client.get_dns_records(zone_id, name=full_domain, record_type="A")
            if existing_records:
                existing_ips = [record["content"] for record in existing_records]
                self.logger.info("  Existing DNS records: %s", ", ".join(existing_ips))
            else:
                self.logger.info("  Existing DNS records: None")

        self.logger.info("Initialization complete")

    async def perform_health_check(self) -> None:
        self.logger.info("Starting health check cycle")

        try:
            configured_ips = self._get_all_configured_ips()

            all_nodes = await self.node_monitor.check_all_nodes()
            configured_nodes = [node for node in all_nodes if node.address in configured_ips]

            healthy_nodes = [node for node in configured_nodes if node.is_healthy]
            unhealthy_nodes = [node for node in configured_nodes if not node.is_healthy]
            healthy_addresses = {node.address for node in healthy_nodes}

            self.logger.info(
                "Nodes: %s/%s online, %s unhealthy",
                len(healthy_nodes),
                len(configured_nodes),
                len(unhealthy_nodes),
            )

            if unhealthy_nodes:
                unhealthy_info = []
                for node in unhealthy_nodes:
                    reason = []
                    if not node.is_connected:
                        reason.append("disconnected")
                    if node.is_disabled:
                        reason.append("disabled")
                    if not node.xray_version:
                        reason.append("no xray")
                    unhealthy_info.append(f"{node.address} ({', '.join(reason)})")
                self.logger.info("Unhealthy nodes: %s", "; ".join(unhealthy_info))

            self._check_node_transitions(configured_nodes)
            self._check_critical_state(configured_nodes, unhealthy_nodes)
            self._emit_observer_status_events()

            users_by_ip: Dict[str, int] = {}
            node_by_ip: Dict[str, object] = {}
            for node in configured_nodes:
                users_by_ip[node.address] = node.users_online
                node_by_ip[node.address] = node

            if self.config.lb_enabled:
                self.logger.info("[LB] users_by_ip: %s", users_by_ip)

            await self._sync_all_zones(healthy_addresses, users_by_ip, node_by_ip)

            self.logger.info("Health check cycle completed")

        except Exception as exc:
            self.logger.error("Error during health check: %s", exc, exc_info=True)
            if self.notifier and self.config.telegram_notify_errors:
                from .telegram import HealthCheckError

                self.notifier.notify_health_check_error(HealthCheckError(error_message=str(exc)))
            raise

    def _emit_observer_status_events(self) -> None:
        if not self.observer_controller:
            return

        for event in self.observer_controller.pop_events():
            self.logger.warning(
                "Observer scope=%s observer=%s status=%s detail=%s",
                event.scope,
                event.observer_id,
                event.status,
                event.detail or "-",
            )
            if self.notifier and self.config.telegram_enabled:
                self.notifier.notify_observer_status_change(event)

    def _get_all_configured_ips(self) -> Set[str]:
        configured_ips = set()
        for zone in self.config.get_all_zones():
            configured_ips.update(zone["ips"])
        return configured_ips

    async def _sync_all_zones(
        self,
        healthy_addresses: Set[str],
        users_by_ip: Dict[str, int] | None = None,
        node_by_ip: Dict[str, object] | None = None,
    ) -> None:
        users_by_ip = users_by_ip or {}
        node_by_ip = node_by_ip or {}

        for zone in self.config.get_all_zones():
            domain = zone["domain"]
            zone_name = zone["name"]
            configured_ips = zone["ips"]

            zone_id = await self._get_zone_id(domain)
            if not zone_id:
                self.logger.warning("Could not find zone_id for domain %s, skipping", domain)
                continue

            effective_healthy = self._apply_capacity_filtering(
                zone_name=zone_name,
                domain=domain,
                configured_ips=configured_ips,
                healthy_addresses=healthy_addresses,
                users_by_ip=users_by_ip,
                node_by_ip=node_by_ip,
            )

            observer_decision = None
            observer_scope = zone.get("observer_scope")
            if self.observer_controller and observer_scope:
                observer_decision = self.observer_controller.evaluate_zone(
                    observer_scope=observer_scope,
                    configured_ips=configured_ips,
                    base_eligible_ips=effective_healthy,
                    min_active_nodes=self.config.lb_min_active_nodes,
                )
                self._log_observer_decision(zone_name=zone_name, domain=domain, decision=observer_decision)
                self._emit_zone_observer_notifications(
                    zone_name=zone_name,
                    domain=domain,
                    decision=observer_decision,
                    node_by_ip=node_by_ip,
                )
                if not observer_decision.shadow_mode:
                    effective_healthy = set(effective_healthy) - observer_decision.effective_drained_ips

            await self.dns_manager.sync_dns_records(
                zone_id=zone_id,
                zone_name=zone_name,
                domain=domain,
                configured_ips=configured_ips,
                healthy_ips=effective_healthy,
                ttl=zone["ttl"],
                proxied=zone["proxied"],
            )

    def _apply_capacity_filtering(
        self,
        zone_name: str,
        domain: str,
        configured_ips: List[str],
        healthy_addresses: Set[str],
        users_by_ip: Dict[str, int],
        node_by_ip: Dict[str, object],
    ) -> Set[str]:
        full_domain = f"{zone_name}.{domain}"

        if not self.config.lb_enabled:
            self.logger.info("[LB] %s: LB is DISABLED in config", full_domain)
            return healthy_addresses

        max_users = self.config.lb_max_users
        recover_users = self.config.lb_recover_users
        min_active = self.config.lb_min_active_nodes

        self.logger.info(
            "[LB] %s: enabled=True, max=%s, recover=%s, min_active=%s",
            full_domain,
            max_users,
            recover_users,
            min_active,
        )

        zone_healthy_ips = [ip for ip in configured_ips if ip in healthy_addresses]
        effective = set(healthy_addresses)

        self.logger.info(
            "[LB] %s: configured_ips=%s, zone_healthy_ips=%s, overloaded=%s",
            full_domain,
            configured_ips,
            zone_healthy_ips,
            self._overloaded_ips,
        )

        capacity_info = []
        for ip in zone_healthy_ips:
            users = users_by_ip.get(ip, 0)
            if ip in self._overloaded_ips:
                capacity_info.append(f"{ip} ({users} users throttled)")
            else:
                capacity_info.append(f"{ip} ({users} users ok)")
        if capacity_info:
            self.logger.info("[LB] %s: capacity: %s", full_domain, ", ".join(capacity_info))

        for ip in zone_healthy_ips:
            users = users_by_ip.get(ip, 0)
            if users > max_users and ip not in self._overloaded_ips:
                active_count = sum(
                    1 for zone_ip in zone_healthy_ips if zone_ip in effective and zone_ip not in self._overloaded_ips
                )
                if active_count <= min_active:
                    self.logger.warning(
                        "%s: %s overloaded (%s users) but keeping active (min-active-nodes=%s)",
                        full_domain,
                        ip,
                        users,
                        min_active,
                    )
                    continue

                self._overloaded_ips.add(ip)
                effective.discard(ip)
                self.logger.info("%s: throttled %s (%s users > %s max)", full_domain, ip, users, max_users)

                node = node_by_ip.get(ip)
                if self.notifier and node:
                    from .telegram import CapacityChange

                    self.notifier.notify_capacity_change(
                        CapacityChange(
                            node_name=getattr(node, "name", ip),
                            node_address=ip,
                            users_online=users,
                            threshold=max_users,
                            action="throttled",
                            zone_name=zone_name,
                            domain=domain,
                        )
                    )

        for ip in list(self._overloaded_ips):
            if ip not in configured_ips:
                continue
            if ip not in healthy_addresses:
                continue

            users = users_by_ip.get(ip, 0)
            if users < recover_users:
                self._overloaded_ips.discard(ip)
                effective.add(ip)
                self.logger.info("%s: restored %s (%s users < %s recover)", full_domain, ip, users, recover_users)

                node = node_by_ip.get(ip)
                if self.notifier and node:
                    from .telegram import CapacityChange

                    self.notifier.notify_capacity_change(
                        CapacityChange(
                            node_name=getattr(node, "name", ip),
                            node_address=ip,
                            users_online=users,
                            threshold=recover_users,
                            action="restored",
                            zone_name=zone_name,
                            domain=domain,
                        )
                    )
            else:
                effective.discard(ip)

        return effective

    def _log_observer_decision(self, zone_name: str, domain: str, decision: ObserverZoneDecision) -> None:
        full_domain = f"{zone_name}.{domain}"
        if not decision.scope:
            return

        self.logger.info(
            "[OBS] %s: scope=%s sequence=%s stale=%s shadow=%s mass_freeze=%s effective_drained=%s blocked=%s",
            full_domain,
            decision.scope,
            decision.sequence,
            decision.stale,
            decision.shadow_mode,
            decision.mass_freeze_active,
            sorted(decision.effective_drained_ips),
            sorted(decision.blocked_ips),
        )

    def _emit_zone_observer_notifications(
        self,
        zone_name: str,
        domain: str,
        decision: ObserverZoneDecision,
        node_by_ip: Dict[str, object],
    ) -> None:
        if not self.notifier or not decision.scope:
            return

        from .telegram import ObserverDecisionChange

        full_domain = f"{zone_name}.{domain}"
        previous = self._observer_zone_state.get(
            full_domain,
            {
                "drained": set(),
                "blocked": set(),
                "force_active": set(),
                "force_drained": set(),
                "shadow_mode": decision.shadow_mode,
            },
        )

        current_drained = set(decision.effective_drained_ips)
        previous_drained = set(previous.get("drained", set()))
        current_blocked = set(decision.blocked_ips)
        previous_blocked = set(previous.get("blocked", set()))
        current_force_active = set(decision.force_active_effective_ips)
        current_force_drained = set(decision.force_drained_effective_ips)
        previous_force_active = set(previous.get("force_active", set()))
        previous_force_drained = set(previous.get("force_drained", set()))
        previous_shadow_mode = bool(previous.get("shadow_mode", decision.shadow_mode))

        for ip in sorted(current_drained - previous_drained):
            node = node_by_ip.get(ip)
            self.notifier.notify_observer_decision_change(
                ObserverDecisionChange(
                    scope=decision.scope,
                    zone_name=zone_name,
                    domain=domain,
                    ip_address=ip,
                    node_name=getattr(node, "name", ip),
                    action="shadow_drained" if decision.shadow_mode else "drained",
                    reasons=decision.reasons_by_ip.get(ip, []),
                )
            )

        for ip in sorted(previous_drained - current_drained):
            node = node_by_ip.get(ip)
            self.notifier.notify_observer_decision_change(
                ObserverDecisionChange(
                    scope=decision.scope,
                    zone_name=zone_name,
                    domain=domain,
                    ip_address=ip,
                    node_name=getattr(node, "name", ip),
                    action="shadow_restored" if previous_shadow_mode else "restored",
                    reasons=decision.reasons_by_ip.get(ip, []),
                )
            )

        for ip in sorted(current_blocked - previous_blocked):
            node = node_by_ip.get(ip)
            self.notifier.notify_observer_decision_change(
                ObserverDecisionChange(
                    scope=decision.scope,
                    zone_name=zone_name,
                    domain=domain,
                    ip_address=ip,
                    node_name=getattr(node, "name", ip),
                    action="blocked",
                    reasons=decision.reasons_by_ip.get(ip, []),
                    detail=f"min-active-nodes={self.config.lb_min_active_nodes}",
                )
            )

        for ip in sorted(current_force_active - previous_force_active):
            node = node_by_ip.get(ip)
            self.notifier.notify_observer_decision_change(
                ObserverDecisionChange(
                    scope=decision.scope,
                    zone_name=zone_name,
                    domain=domain,
                    ip_address=ip,
                    node_name=getattr(node, "name", ip),
                    action="force_active",
                    reasons=decision.reasons_by_ip.get(ip, []),
                )
            )

        for ip in sorted(current_force_drained - previous_force_drained):
            node = node_by_ip.get(ip)
            self.notifier.notify_observer_decision_change(
                ObserverDecisionChange(
                    scope=decision.scope,
                    zone_name=zone_name,
                    domain=domain,
                    ip_address=ip,
                    node_name=getattr(node, "name", ip),
                    action="force_drained",
                    reasons=decision.reasons_by_ip.get(ip, []),
                )
            )

        self._observer_zone_state[full_domain] = {
            "drained": current_drained,
            "blocked": current_blocked,
            "force_active": current_force_active,
            "force_drained": current_force_drained,
            "shadow_mode": decision.shadow_mode,
        }

    async def _get_zone_id(self, domain: str) -> Optional[str]:
        if domain in self._zone_id_cache:
            return self._zone_id_cache[domain]

        zone_id = await self.cloudflare_client.get_zone_id_by_domain(domain)
        if zone_id:
            self._zone_id_cache[domain] = zone_id

        return zone_id

    def _check_node_transitions(self, nodes) -> None:
        if not self.notifier or not self.config.telegram_notify_node_changes:
            return

        from .telegram import NodeStateChange, NodeStats

        total = len(nodes)
        online = sum(1 for node in nodes if node.is_healthy)
        disabled = sum(1 for node in nodes if node.is_disabled)
        stats = NodeStats(total=total, online=online, disabled=disabled)

        for node in nodes:
            previous_healthy = self._previous_node_states.get(node.address)
            current_healthy = node.is_healthy

            if previous_healthy is None or previous_healthy == current_healthy:
                self._previous_node_states[node.address] = current_healthy
                continue

            reason = None
            if not current_healthy:
                reasons = []
                if not node.is_connected:
                    reasons.append("disconnected")
                if node.is_disabled:
                    reasons.append("disabled")
                if not node.xray_version:
                    reasons.append("no xray")
                reason = ", ".join(reasons) if reasons else "unknown"

            self.notifier.notify_node_state_change(
                NodeStateChange(
                    node_name=node.name,
                    node_address=node.address,
                    previous_healthy=previous_healthy,
                    current_healthy=current_healthy,
                    stats=stats,
                    reason=reason,
                )
            )
            self._previous_node_states[node.address] = current_healthy

    def _check_critical_state(self, configured_nodes, unhealthy_nodes) -> None:
        if not self.notifier or not self.config.telegram_notify_critical:
            return

        all_down = 0 < len(configured_nodes) == len(unhealthy_nodes)
        if all_down and not self._previous_all_down:
            from .telegram import CriticalState

            self.notifier.notify_critical_state(
                CriticalState(total_nodes=len(configured_nodes), down_nodes=[node.address for node in unhealthy_nodes])
            )

        self._previous_all_down = all_down
