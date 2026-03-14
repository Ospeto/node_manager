from dataclasses import dataclass
from typing import List, Optional


@dataclass
class NodeStats:
    total: int
    online: int
    disabled: int


@dataclass
class NodeStateChange:
    node_name: str
    node_address: str
    previous_healthy: bool
    current_healthy: bool
    stats: Optional[NodeStats] = None
    reason: Optional[str] = None


@dataclass
class DNSChange:
    domain: str
    zone_name: str
    ip_address: str
    action: str  # "added" or "removed"


@dataclass
class DNSError:
    domain: str
    zone_name: str
    ip_address: str
    action: str
    error_message: str


@dataclass
class CriticalState:
    total_nodes: int
    down_nodes: List[str]


@dataclass
class HealthCheckError:
    error_message: str


@dataclass
class CapacityChange:
    node_name: str
    node_address: str
    users_online: int
    threshold: int
    action: str  # "throttled" or "restored"
    zone_name: str
    domain: str


@dataclass
class ObserverStatusChange:
    scope: str
    observer_id: str
    status: str  # "stale" | "recovered" | "extended_stale" | "mass_freeze" | "mass_freeze_cleared"
    detail: str = ""


@dataclass
class ObserverDecisionChange:
    scope: str
    zone_name: str
    domain: str
    ip_address: str
    node_name: str
    action: str  # drained | restored | blocked | shadow_drained | shadow_restored | force_active | force_drained
    reasons: List[str]
    detail: str = ""
