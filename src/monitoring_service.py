from typing import TYPE_CHECKING, Dict, List, Optional, Set

from .config import Config
from .remnawave import NodeMonitor
from .cloudflare_dns import CloudflareClient, DNSManager
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
    ):
        self.config = config
        self.node_monitor = node_monitor
        self.cloudflare_client = cloudflare_client
        self.dns_manager = dns_manager
        self.notifier = notifier
        self.logger = get_logger(__name__)
        self._zone_id_cache: Dict[str, str] = {}
        self._previous_node_states: Dict[str, bool] = {}
        self._previous_all_down: bool = False
        self._overloaded_ips: Set[str] = set()  # IPs removed due to capacity

    async def initialize_and_print_zones(self) -> None:
        self.logger.info("Initializing zones")

        current_domain = None
        for zone in self.config.get_all_zones():
            domain = zone["domain"]

            if domain != current_domain:
                zone_id = await self._get_zone_id(domain)
                if not zone_id:
                    self.logger.warning(f"Could not find zone_id for domain {domain}")
                    continue
                self.logger.info(f"Domain: {domain}, Zone ID: {zone_id}")
                current_domain = domain

            full_domain = f"{zone['name']}.{domain}"
            self.logger.info(f"  Zone: {full_domain}, TTL: {zone['ttl']}, Proxied: {zone['proxied']}")

            self.logger.info(f"  Configured IPs: {', '.join(zone['ips'])}")

            zone_id = await self._get_zone_id(domain)
            existing_records = await self.cloudflare_client.get_dns_records(zone_id, name=full_domain, record_type="A")
            if existing_records:
                existing_ips = [record["content"] for record in existing_records]
                self.logger.info(f"  Existing DNS records: {', '.join(existing_ips)}")
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
                f"Nodes: {len(healthy_nodes)}/{len(configured_nodes)} online, {len(unhealthy_nodes)} unhealthy"
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
                self.logger.info(f"Unhealthy nodes: {'; '.join(unhealthy_info)}")

            self._check_node_transitions(configured_nodes)
            self._check_critical_state(configured_nodes, unhealthy_nodes)

            # Build user count map for capacity-based load balancing
            users_by_ip: Dict[str, int] = {}
            node_by_ip: Dict[str, object] = {}
            for node in configured_nodes:
                users_by_ip[node.address] = node.users_online
                node_by_ip[node.address] = node

            if self.config.lb_enabled:
                self.logger.info(f"[LB] users_by_ip: {users_by_ip}")

            await self._sync_all_zones(healthy_addresses, users_by_ip, node_by_ip)

            self.logger.info("Health check cycle completed")

        except Exception as e:
            self.logger.error(f"Error during health check: {e}", exc_info=True)
            if self.notifier and self.config.telegram_notify_errors:
                from .telegram import HealthCheckError

                self.notifier.notify_health_check_error(HealthCheckError(error_message=str(e)))
            raise

    def _get_all_configured_ips(self) -> Set[str]:
        configured_ips = set()
        for zone in self.config.get_all_zones():
            configured_ips.update(zone["ips"])
        return configured_ips

    async def _sync_all_zones(
        self,
        healthy_addresses: Set[str],
        users_by_ip: Dict[str, int] = None,
        node_by_ip: Dict[str, object] = None,
    ) -> None:
        if users_by_ip is None:
            users_by_ip = {}
        if node_by_ip is None:
            node_by_ip = {}

        for zone in self.config.get_all_zones():
            domain = zone["domain"]
            zone_name = zone["name"]
            configured_ips = zone["ips"]

            zone_id = await self._get_zone_id(domain)
            if not zone_id:
                self.logger.warning(f"Could not find zone_id for domain {domain}, skipping")
                continue

            # Apply capacity-based filtering if enabled
            effective_healthy = self._apply_capacity_filtering(
                zone_name=zone_name,
                domain=domain,
                configured_ips=configured_ips,
                healthy_addresses=healthy_addresses,
                users_by_ip=users_by_ip,
                node_by_ip=node_by_ip,
            )

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
        """Filter healthy IPs based on capacity thresholds.

        Uses hysteresis: remove at max_users, re-add at recover_users.
        Enforces min_active_nodes per zone.
        """
        if not self.config.lb_enabled:
            return healthy_addresses

        max_users = self.config.lb_max_users
        recover_users = self.config.lb_recover_users
        min_active = self.config.lb_min_active_nodes
        full_domain = f"{zone_name}.{domain}"

        self.logger.info(
            f"[LB] {full_domain}: enabled=True, max={max_users}, recover={recover_users}, min_active={min_active}"
        )

        # Only consider IPs that belong to this zone AND are healthy
        zone_healthy_ips = [ip for ip in configured_ips if ip in healthy_addresses]
        effective = set(healthy_addresses)  # Start with all healthy

        self.logger.info(
            f"[LB] {full_domain}: configured_ips={configured_ips}, "
            f"zone_healthy_ips={zone_healthy_ips}, overloaded={self._overloaded_ips}"
        )

        # Log capacity info for this zone
        capacity_info = []
        for ip in zone_healthy_ips:
            users = users_by_ip.get(ip, 0)
            if ip in self._overloaded_ips:
                capacity_info.append(f"{ip} ({users} users ⚡)")
            else:
                capacity_info.append(f"{ip} ({users} users ✓)")
        if capacity_info:
            self.logger.info(f"[LB] {full_domain}: capacity: {', '.join(capacity_info)}")

        # Phase 1: Check for nodes that should be THROTTLED (over max_users)
        for ip in zone_healthy_ips:
            users = users_by_ip.get(ip, 0)
            if users > max_users and ip not in self._overloaded_ips:
                # Count how many zone nodes would remain active
                active_count = sum(
                    1 for zip_ip in zone_healthy_ips
                    if zip_ip in effective and zip_ip not in self._overloaded_ips
                )
                if active_count <= min_active:
                    self.logger.warning(
                        f"{full_domain}: {ip} overloaded ({users} users) but keeping active "
                        f"(min-active-nodes={min_active})"
                    )
                    continue

                self._overloaded_ips.add(ip)
                effective.discard(ip)
                self.logger.info(
                    f"{full_domain}: throttled {ip} ({users} users > {max_users} max)"
                )

                # Send Telegram notification
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

        # Phase 2: Check for nodes that should be RESTORED (under recover_users)
        for ip in list(self._overloaded_ips):
            if ip not in configured_ips:
                continue  # Not in this zone
            if ip not in healthy_addresses:
                continue  # Node went unhealthy, let normal logic handle it

            users = users_by_ip.get(ip, 0)
            if users < recover_users:
                self._overloaded_ips.discard(ip)
                effective.add(ip)
                self.logger.info(
                    f"{full_domain}: restored {ip} ({users} users < {recover_users} recover)"
                )

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
                # Still overloaded, keep removed
                effective.discard(ip)

        return effective

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
        online = sum(1 for n in nodes if n.is_healthy)
        disabled = sum(1 for n in nodes if n.is_disabled)
        stats = NodeStats(total=total, online=online, disabled=disabled)

        for node in nodes:
            prev_healthy = self._previous_node_states.get(node.address)
            curr_healthy = node.is_healthy

            if prev_healthy is None or prev_healthy == curr_healthy:
                self._previous_node_states[node.address] = curr_healthy
                continue

            reason = None
            if not curr_healthy:
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
                    previous_healthy=prev_healthy,
                    current_healthy=curr_healthy,
                    stats=stats,
                    reason=reason,
                )
            )

            self._previous_node_states[node.address] = curr_healthy

    def _check_critical_state(self, configured_nodes, unhealthy_nodes) -> None:
        if not self.notifier or not self.config.telegram_notify_critical:
            return

        all_down = 0 < len(configured_nodes) == len(unhealthy_nodes)

        if all_down and not self._previous_all_down:
            from .telegram import CriticalState

            self.notifier.notify_critical_state(
                CriticalState(total_nodes=len(configured_nodes), down_nodes=[n.address for n in unhealthy_nodes])
            )

        self._previous_all_down = all_down
