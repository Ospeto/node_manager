from typing import List, Optional
from uuid import UUID


from .client import RemnawaveClient
from ..utils.logger import get_logger


class NodeStatus:
    def __init__(
        self,
        name: str,
        address: str,
        is_healthy: bool,
        is_connected: bool,
        is_disabled: bool,
        xray_version: Optional[str],
        xray_uptime: Optional[int] = None,
        port: Optional[int] = None,
        users_online: int = 0,
        uuid: Optional[str] = None,
    ):
        self.name = name
        self.address = address
        self.is_healthy = is_healthy
        self.is_connected = is_connected
        self.is_disabled = is_disabled
        self.xray_version = xray_version
        self.xray_uptime = xray_uptime
        self.port = port
        self.users_online = users_online
        self.uuid = uuid

    def __repr__(self):
        status = "healthy" if self.is_healthy else "unhealthy"
        return f"NodeStatus(name={self.name}, address={self.address}, status={status})"


class NodeMonitor:
    def __init__(self, client: RemnawaveClient):
        self.client = client
        self.logger = get_logger(__name__)

    async def check_all_nodes(self) -> List[NodeStatus]:
        try:
            nodes = await self.client.get_nodes()
            node_statuses = []

            for node in nodes:
                status = NodeStatus(
                    name=node.name,
                    address=node.address,
                    is_healthy=self.client.is_node_healthy(node),
                    is_connected=node.is_connected,
                    is_disabled=node.is_disabled,
                    xray_version=node.xray_version,
                    xray_uptime=node.xray_uptime,
                    port=node.port,
                    users_online=node.users_online or 0,
                    uuid=str(node.uuid) if isinstance(node.uuid, UUID) else node.uuid,
                )
                node_statuses.append(status)

                self.logger.debug(f"Node {node.name} ({node.address}): {status}")

            healthy_count = sum(1 for s in node_statuses if s.is_healthy)
            unhealthy_count = len(node_statuses) - healthy_count
            self.logger.info(f"Fetched {len(node_statuses)} nodes: {healthy_count} online, {unhealthy_count} unhealthy")

            return node_statuses

        except Exception as e:
            self.logger.error(f"Error checking nodes: {e}")
            raise

    async def get_healthy_nodes(self) -> List[NodeStatus]:
        all_nodes = await self.check_all_nodes()
        return [node for node in all_nodes if node.is_healthy]

    async def get_unhealthy_nodes(self) -> List[NodeStatus]:
        all_nodes = await self.check_all_nodes()
        return [node for node in all_nodes if not node.is_healthy]

    async def get_node_addresses(self, only_healthy: bool = True) -> List[str]:
        if only_healthy:
            nodes = await self.get_healthy_nodes()
        else:
            nodes = await self.check_all_nodes()

        return [node.address for node in nodes if node.address]
