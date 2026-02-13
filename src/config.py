import os
import re
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv


class Config:
    def __init__(self, config_path: str = "config.yml"):
        load_dotenv()

        self.config_path = Path(config_path)
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path, "r") as f:
            config = yaml.safe_load(f)

        return self._substitute_env_vars(config)

    def _substitute_env_vars(self, config: Any) -> Any:
        if isinstance(config, dict):
            return {k: self._substitute_env_vars(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self._substitute_env_vars(item) for item in config]
        elif isinstance(config, str):
            pattern = re.compile(r"\$\{([^}]+)}")
            matches = pattern.findall(config)
            result = config
            for var_name in matches:
                var_value = os.getenv(var_name, "")
                result = result.replace(f"${{{var_name}}}", var_value)
            return result
        else:
            return config

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        value = self._config

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default

        return value

    @property
    def remnawave_url(self) -> str:
        return os.getenv("REMNAWAVE_API_URL", "")

    @property
    def remnawave_api_key(self) -> str:
        return os.getenv("REMNAWAVE_API_KEY", "")

    @property
    def cloudflare_token(self) -> str:
        return os.getenv("CLOUDFLARE_API_TOKEN", "")

    @property
    def check_interval(self) -> int:
        return self.get("remnawave.check-interval", 30)

    @property
    def domains(self) -> list:
        return self.get("domains", [])

    @property
    def logging_config(self) -> dict:
        return self.get("logging", {})

    @property
    def log_level(self) -> str:
        return self.get("logging.level", "INFO")

    @property
    def telegram_enabled(self) -> bool:
        return self.get("telegram.enabled", False)

    @property
    def telegram_bot_token(self) -> str:
        return os.getenv("TELEGRAM_BOT_TOKEN", "")

    @property
    def telegram_chat_id(self) -> str:
        return os.getenv("TELEGRAM_CHAT_ID", "")

    @property
    def telegram_topic_id(self) -> int | None:
        topic_id = os.getenv("TELEGRAM_TOPIC_ID", "")
        if topic_id and topic_id.strip():
            try:
                return int(topic_id.strip())
            except ValueError:
                return None
        return None

    @property
    def timezone(self) -> str:
        return os.getenv("TIMEZONE", "UTC")

    @property
    def time_format(self) -> str:
        return os.getenv("TIME_FORMAT", "%d.%m.%Y %H:%M:%S")

    @property
    def telegram_locale(self) -> str:
        return self.get("telegram.locale", "en")

    @property
    def telegram_notify_dns_changes(self) -> bool:
        return self.get("telegram.notify.dns_changes", True)

    @property
    def telegram_notify_node_changes(self) -> bool:
        return self.get("telegram.notify.node_changes", True)

    @property
    def telegram_notify_errors(self) -> bool:
        return self.get("telegram.notify.errors", True)

    @property
    def telegram_notify_critical(self) -> bool:
        return self.get("telegram.notify.critical", True)

    def get_all_zones(self) -> list:
        zones = []
        for domain_config in self.domains:
            domain = domain_config.get("domain")
            for zone in domain_config.get("zones", []):
                zone_data = {
                    "domain": domain,
                    "name": zone.get("name"),
                    "ttl": zone.get("ttl", 120),
                    "proxied": zone.get("proxied", False),
                    "ips": zone.get("ips", []),
                }
                zones.append(zone_data)
        return zones
