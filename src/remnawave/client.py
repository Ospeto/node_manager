from typing import List

from remnawave import RemnawaveSDK
from remnawave.models import NodeResponseDto

from ..utils.logger import get_logger


class RemnawaveClient:
    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.logger = get_logger(__name__)
        self.sdk = RemnawaveSDK(base_url=self.api_url, token=self.api_key)

    async def get_nodes(self) -> List[NodeResponseDto]:
        try:
            self.logger.info(f"Fetching nodes from {self.api_url}")

            response = await self.sdk.nodes.get_all_nodes()

            nodes_list = response.root if hasattr(response, "root") else []

            self.logger.info(f"Successfully fetched {len(nodes_list)} nodes")
            return nodes_list
        except Exception as e:
            self.logger.error(f"Error fetching nodes: {e}")
            raise

    @staticmethod
    def is_node_connected(node: NodeResponseDto) -> bool:
        return node.is_connected and node.xray_version is not None

    @staticmethod
    def is_node_disabled(node: NodeResponseDto) -> bool:
        return node.is_disabled

    @staticmethod
    def is_node_healthy(node: NodeResponseDto) -> bool:
        return RemnawaveClient.is_node_connected(node) and not RemnawaveClient.is_node_disabled(node)
