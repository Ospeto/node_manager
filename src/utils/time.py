from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import Config


def format_timestamp(timestamp_str: str, config: Config) -> str:
    dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    dt_local = dt.astimezone(ZoneInfo(config.timezone))
    tz_abbr = dt_local.strftime("%Z")
    return dt_local.strftime(f"{config.time_format} {tz_abbr}")
