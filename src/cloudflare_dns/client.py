import asyncio
import time
from typing import List, Dict, Optional

from cloudflare import AsyncCloudflare

from ..utils.logger import get_logger


class CloudflareClient:
    def __init__(self, api_token: str, rate_limit_delay: float = 0.25, retry_delay: float = 1.0):
        self.api_token = api_token
        self.logger = get_logger(__name__)
        self.cf = AsyncCloudflare(api_token=api_token)
        self.rate_limit_delay = rate_limit_delay
        self.retry_delay = retry_delay
        self._last_request_time: float = 0

    async def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = time.monotonic()

    async def _retry_delay(self, attempt: int) -> None:
        delay = min(self.retry_delay * attempt, 30.0)
        await asyncio.sleep(delay)

    async def get_dns_records(self, zone_id: str, name: str = None, record_type: str = "A") -> List[Dict]:
        attempt = 0
        while True:
            try:
                await self._rate_limit()
                params = {"type": record_type}
                if name:
                    params["name"] = name

                records_list = []
                async for record in self.cf.dns.records.list(zone_id=zone_id, **params):
                    records_list.append(
                        {
                            "id": record.id,
                            "name": record.name,
                            "content": record.content,
                            "type": record.type,
                            "ttl": record.ttl,
                            "proxied": record.proxied,
                        }
                    )

                self.logger.debug(f"Found {len(records_list)} DNS records for zone {zone_id}")
                return records_list

            except Exception as e:
                attempt += 1
                self.logger.error(f"Error fetching DNS records (attempt {attempt}): {e}")
                await self._retry_delay(attempt)

    async def create_dns_record(
        self, zone_id: str, name: str, content: str, record_type: str = "A", ttl: int = 120, proxied: bool = False
    ) -> Dict:
        attempt = 0
        while True:
            try:
                await self._rate_limit()
                record = await self.cf.dns.records.create(
                    zone_id=zone_id, type=record_type, name=name, content=content, ttl=ttl, proxied=proxied
                )
                self.logger.info(f"Created DNS record: {name} -> {content}")
                return {
                    "id": record.id,
                    "name": record.name,
                    "content": record.content,
                    "type": record.type,
                    "ttl": record.ttl,
                    "proxied": record.proxied,
                }

            except Exception as e:
                status_code = getattr(e, "status_code", None)
                if status_code and 400 <= status_code < 500:
                    raise
                attempt += 1
                self.logger.error(f"Error creating DNS record (attempt {attempt}): {e}")
                await self._retry_delay(attempt)

    async def update_dns_record(
        self,
        zone_id: str,
        record_id: str,
        name: str,
        content: str,
        record_type: str = "A",
        ttl: int = 120,
        proxied: bool = False,
    ) -> Dict:
        attempt = 0
        while True:
            try:
                await self._rate_limit()
                record = await self.cf.dns.records.update(
                    dns_record_id=record_id,
                    zone_id=zone_id,
                    type=record_type,
                    name=name,
                    content=content,
                    ttl=ttl,
                    proxied=proxied,
                )
                self.logger.info(f"Updated DNS record: {name} -> {content}")
                return {
                    "id": record.id,
                    "name": record.name,
                    "content": record.content,
                    "type": record.type,
                    "ttl": record.ttl,
                    "proxied": record.proxied,
                }

            except Exception as e:
                attempt += 1
                self.logger.error(f"Error updating DNS record (attempt {attempt}): {e}")
                await self._retry_delay(attempt)

    async def delete_dns_record(self, zone_id: str, record_id: str) -> None:
        attempt = 0
        while True:
            try:
                await self._rate_limit()
                await self.cf.dns.records.delete(dns_record_id=record_id, zone_id=zone_id)
                self.logger.info(f"Deleted DNS record: {record_id}")
                return

            except Exception as e:
                attempt += 1
                self.logger.error(f"Error deleting DNS record (attempt {attempt}): {e}")
                await self._retry_delay(attempt)

    async def get_record_by_name_and_content(
        self, zone_id: str, name: str, content: str, record_type: str = "A"
    ) -> Optional[Dict]:
        records = await self.get_dns_records(zone_id, name=name, record_type=record_type)
        for record in records:
            if record.get("content") == content:
                return record
        return None

    async def get_zone_id_by_domain(self, domain: str) -> Optional[str]:
        attempt = 0
        while True:
            try:
                await self._rate_limit()
                async for zone in self.cf.zones.list(name=domain):
                    zone_id = zone.id
                    self.logger.info(f"Found zone_id for {domain}: {zone_id}")
                    return zone_id

                self.logger.error(f"No zone found for domain: {domain}")
                return None

            except Exception as e:
                attempt += 1
                self.logger.error(f"Error fetching zone for domain {domain} (attempt {attempt}): {e}")
                await self._retry_delay(attempt)
