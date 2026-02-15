"""Unit tests for _apply_capacity_filtering in MonitoringService.

Tests cover:
1. LB disabled → passthrough
2. Normal load → no filtering
3. Overloaded node → throttled (removed from effective)
4. Hysteresis → node stays removed between max and recover thresholds
5. Recovery → node restored below recover threshold
6. Min-active-nodes → prevents removing last node(s)
7. Multi-zone → overloaded_ips don't leak across zones
8. Unhealthy overloaded node → handled by normal health logic, not capacity
9. Edge: exactly at threshold boundaries
10. Edge: all nodes overloaded, min-active keeps them
"""

import sys
import os
from unittest.mock import MagicMock
from dataclasses import dataclass


@dataclass
class FakeNode:
    name: str
    address: str
    users_online: int = 0


class FakeConfig:
    """Minimal config stub for testing capacity filtering."""
    def __init__(self, enabled=True, max_users=50, recover_users=30, min_active=1):
        self._enabled = enabled
        self._max = max_users
        self._recover = recover_users
        self._min = min_active

    @property
    def lb_enabled(self):
        return self._enabled

    @property
    def lb_max_users(self):
        return self._max

    @property
    def lb_recover_users(self):
        return self._recover

    @property
    def lb_min_active_nodes(self):
        return self._min


class CapacityFilteringHarness:
    """
    Standalone test harness that contains the exact _apply_capacity_filtering logic
    from MonitoringService, without requiring the full package import.
    """
    def __init__(self, config):
        self.config = config
        self.logger = MagicMock()
        self.notifier = None
        self._overloaded_ips = set()

    def _apply_capacity_filtering(self, zone_name, domain, configured_ips,
                                   healthy_addresses, users_by_ip, node_by_ip):
        if not self.config.lb_enabled:
            return healthy_addresses

        max_users = self.config.lb_max_users
        recover_users = self.config.lb_recover_users
        min_active = self.config.lb_min_active_nodes
        full_domain = f"{zone_name}.{domain}"

        zone_healthy_ips = [ip for ip in configured_ips if ip in healthy_addresses]
        effective = set(healthy_addresses)

        capacity_info = []
        for ip in zone_healthy_ips:
            users = users_by_ip.get(ip, 0)
            if ip in self._overloaded_ips:
                capacity_info.append(f"{ip} ({users} users ⚡)")
            else:
                capacity_info.append(f"{ip} ({users} users ✓)")
        if capacity_info:
            self.logger.info(f"{full_domain}: capacity: {', '.join(capacity_info)}")

        # Phase 1: THROTTLE
        for ip in zone_healthy_ips:
            users = users_by_ip.get(ip, 0)
            if users > max_users and ip not in self._overloaded_ips:
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

        # Phase 2: RESTORE
        for ip in list(self._overloaded_ips):
            if ip not in configured_ips:
                continue
            if ip not in healthy_addresses:
                continue

            users = users_by_ip.get(ip, 0)
            if users < recover_users:
                self._overloaded_ips.discard(ip)
                effective.add(ip)
                self.logger.info(
                    f"{full_domain}: restored {ip} ({users} users < {recover_users} recover)"
                )
            else:
                effective.discard(ip)

        return effective


def make_service(config=None):
    if config is None:
        config = FakeConfig()
    return CapacityFilteringHarness(config)


# ─────────────────────────────────────────────
#  Test 1: LB disabled → passthrough
# ─────────────────────────────────────────────
def test_lb_disabled_passthrough():
    config = FakeConfig(enabled=False)
    svc = make_service(config)

    healthy = {"1.1.1.1", "2.2.2.2"}
    result = svc._apply_capacity_filtering(
        zone_name="s1", domain="example.com",
        configured_ips=["1.1.1.1", "2.2.2.2"],
        healthy_addresses=healthy,
        users_by_ip={"1.1.1.1": 999, "2.2.2.2": 999},
        node_by_ip={},
    )
    assert result is healthy, "Should return exact same set object when disabled"
    print("✅ Test 1: LB disabled passthrough")


# ─────────────────────────────────────────────
#  Test 2: Normal load → no filtering
# ─────────────────────────────────────────────
def test_normal_load_no_filtering():
    svc = make_service(FakeConfig(max_users=50, recover_users=30))

    result = svc._apply_capacity_filtering(
        zone_name="s1", domain="example.com",
        configured_ips=["1.1.1.1", "2.2.2.2"],
        healthy_addresses={"1.1.1.1", "2.2.2.2"},
        users_by_ip={"1.1.1.1": 10, "2.2.2.2": 20},
        node_by_ip={},
    )
    assert result == {"1.1.1.1", "2.2.2.2"}, f"Expected both IPs, got {result}"
    assert len(svc._overloaded_ips) == 0
    print("✅ Test 2: Normal load, no filtering")


# ─────────────────────────────────────────────
#  Test 3: Overloaded node → throttled
# ─────────────────────────────────────────────
def test_overloaded_node_throttled():
    svc = make_service(FakeConfig(max_users=50, recover_users=30))

    result = svc._apply_capacity_filtering(
        zone_name="s1", domain="example.com",
        configured_ips=["1.1.1.1", "2.2.2.2"],
        healthy_addresses={"1.1.1.1", "2.2.2.2"},
        users_by_ip={"1.1.1.1": 60, "2.2.2.2": 20},
        node_by_ip={"1.1.1.1": FakeNode("node1", "1.1.1.1", 60)},
    )
    assert "1.1.1.1" not in result, "Overloaded IP should be removed"
    assert "2.2.2.2" in result, "Non-overloaded IP should remain"
    assert "1.1.1.1" in svc._overloaded_ips, "Should be tracked as overloaded"
    print("✅ Test 3: Overloaded node throttled")


# ─────────────────────────────────────────────
#  Test 4: Hysteresis — stays removed between thresholds
# ─────────────────────────────────────────────
def test_hysteresis_between_thresholds():
    svc = make_service(FakeConfig(max_users=50, recover_users=30))

    # First cycle: node goes over max → throttled
    svc._apply_capacity_filtering(
        zone_name="s1", domain="example.com",
        configured_ips=["1.1.1.1", "2.2.2.2"],
        healthy_addresses={"1.1.1.1", "2.2.2.2"},
        users_by_ip={"1.1.1.1": 60, "2.2.2.2": 20},
        node_by_ip={},
    )
    assert "1.1.1.1" in svc._overloaded_ips

    # Second cycle: node drops to 40 (below max=50, but above recover=30)
    result = svc._apply_capacity_filtering(
        zone_name="s1", domain="example.com",
        configured_ips=["1.1.1.1", "2.2.2.2"],
        healthy_addresses={"1.1.1.1", "2.2.2.2"},
        users_by_ip={"1.1.1.1": 40, "2.2.2.2": 20},
        node_by_ip={},
    )
    assert "1.1.1.1" not in result, "Should stay removed (between thresholds)"
    assert "1.1.1.1" in svc._overloaded_ips, "Should still be tracked as overloaded"
    print("✅ Test 4: Hysteresis — stays removed between thresholds")


# ─────────────────────────────────────────────
#  Test 5: Recovery — node restored below recover threshold
# ─────────────────────────────────────────────
def test_recovery_below_threshold():
    svc = make_service(FakeConfig(max_users=50, recover_users=30))

    # Manually mark as overloaded (simulating previous cycle)
    svc._overloaded_ips.add("1.1.1.1")

    result = svc._apply_capacity_filtering(
        zone_name="s1", domain="example.com",
        configured_ips=["1.1.1.1", "2.2.2.2"],
        healthy_addresses={"1.1.1.1", "2.2.2.2"},
        users_by_ip={"1.1.1.1": 20, "2.2.2.2": 10},
        node_by_ip={"1.1.1.1": FakeNode("node1", "1.1.1.1", 20)},
    )
    assert "1.1.1.1" in result, "Should be restored"
    assert "1.1.1.1" not in svc._overloaded_ips, "Should no longer be tracked"
    print("✅ Test 5: Recovery below threshold")


# ─────────────────────────────────────────────
#  Test 6: Min-active-nodes prevents removing last node
# ─────────────────────────────────────────────
def test_min_active_nodes():
    svc = make_service(FakeConfig(max_users=50, recover_users=30, min_active=1))

    # Only 1 node in zone, it's overloaded → should NOT be removed
    result = svc._apply_capacity_filtering(
        zone_name="s1", domain="example.com",
        configured_ips=["1.1.1.1"],
        healthy_addresses={"1.1.1.1"},
        users_by_ip={"1.1.1.1": 100},
        node_by_ip={},
    )
    assert "1.1.1.1" in result, "Should keep the last node even when overloaded"
    assert "1.1.1.1" not in svc._overloaded_ips, "Should NOT be marked as overloaded"
    print("✅ Test 6: Min-active-nodes prevents removing last node")


# ─────────────────────────────────────────────
#  Test 7: Min-active=2, two overloaded nodes → only remove 1
# ─────────────────────────────────────────────
def test_min_active_nodes_two():
    svc = make_service(FakeConfig(max_users=50, recover_users=30, min_active=2))

    result = svc._apply_capacity_filtering(
        zone_name="s1", domain="example.com",
        configured_ips=["1.1.1.1", "2.2.2.2", "3.3.3.3"],
        healthy_addresses={"1.1.1.1", "2.2.2.2", "3.3.3.3"},
        users_by_ip={"1.1.1.1": 60, "2.2.2.2": 70, "3.3.3.3": 10},
        node_by_ip={},
    )
    # Should throttle at most 1 of the overloaded nodes (3 healthy, min_active=2)
    throttled_count = sum(1 for ip in ["1.1.1.1", "2.2.2.2"] if ip not in result)
    assert throttled_count == 1, f"Expected 1 throttled, got {throttled_count}"
    assert "3.3.3.3" in result, "Non-overloaded node should remain"
    print("✅ Test 7: Min-active=2, removes at most 1 overloaded")


# ─────────────────────────────────────────────
#  Test 8: Overloaded IP not in this zone → skip
# ─────────────────────────────────────────────
def test_overloaded_ip_different_zone():
    svc = make_service(FakeConfig(max_users=50, recover_users=30))

    # An IP was overloaded in a different zone
    svc._overloaded_ips.add("9.9.9.9")

    result = svc._apply_capacity_filtering(
        zone_name="s1", domain="example.com",
        configured_ips=["1.1.1.1"],
        healthy_addresses={"1.1.1.1"},
        users_by_ip={"1.1.1.1": 10},
        node_by_ip={},
    )
    assert "1.1.1.1" in result
    assert "9.9.9.9" in svc._overloaded_ips, "Should not have removed other zone's IP"
    print("✅ Test 8: Overloaded IP in different zone — skipped")


# ─────────────────────────────────────────────
#  Test 9: Unhealthy overloaded node → stays in overloaded_ips but skipped
# ─────────────────────────────────────────────
def test_unhealthy_overloaded_node():
    svc = make_service(FakeConfig(max_users=50, recover_users=30))

    svc._overloaded_ips.add("1.1.1.1")

    # Node is now unhealthy (not in healthy_addresses)
    result = svc._apply_capacity_filtering(
        zone_name="s1", domain="example.com",
        configured_ips=["1.1.1.1", "2.2.2.2"],
        healthy_addresses={"2.2.2.2"},  # 1.1.1.1 unhealthy
        users_by_ip={"2.2.2.2": 10},
        node_by_ip={},
    )
    assert "1.1.1.1" not in result, "Unhealthy node should not be in result"
    assert "2.2.2.2" in result
    # The IP stays in overloaded_ips (skipped because unhealthy)
    assert "1.1.1.1" in svc._overloaded_ips, "Should remain tracked (skipped, not cleared)"
    print("✅ Test 9: Unhealthy overloaded node correctly skipped")


# ─────────────────────────────────────────────
#  Test 10: Exact boundary — users == max_users (not >)
# ─────────────────────────────────────────────
def test_exact_boundary_max():
    svc = make_service(FakeConfig(max_users=50, recover_users=30))

    result = svc._apply_capacity_filtering(
        zone_name="s1", domain="example.com",
        configured_ips=["1.1.1.1", "2.2.2.2"],
        healthy_addresses={"1.1.1.1", "2.2.2.2"},
        users_by_ip={"1.1.1.1": 50, "2.2.2.2": 20},  # exactly at threshold
        node_by_ip={},
    )
    assert "1.1.1.1" in result, "Exactly at max should NOT be throttled (> not >=)"
    print("✅ Test 10: Exact boundary — at max, not throttled")


# ─────────────────────────────────────────────
#  Test 11: Exact boundary — users == recover_users (not <)
# ─────────────────────────────────────────────
def test_exact_boundary_recover():
    svc = make_service(FakeConfig(max_users=50, recover_users=30))
    svc._overloaded_ips.add("1.1.1.1")

    result = svc._apply_capacity_filtering(
        zone_name="s1", domain="example.com",
        configured_ips=["1.1.1.1", "2.2.2.2"],
        healthy_addresses={"1.1.1.1", "2.2.2.2"},
        users_by_ip={"1.1.1.1": 30, "2.2.2.2": 10},  # exactly at recover
        node_by_ip={},
    )
    assert "1.1.1.1" not in result, "Exactly at recover should NOT be restored (< not <=)"
    assert "1.1.1.1" in svc._overloaded_ips
    print("✅ Test 11: Exact boundary — at recover, stays removed")


# ─────────────────────────────────────────────
#  Test 12: Multi-cycle full lifecycle
# ─────────────────────────────────────────────
def test_full_lifecycle():
    svc = make_service(FakeConfig(max_users=50, recover_users=30))

    # Cycle 1: Normal
    r = svc._apply_capacity_filtering(
        zone_name="s1", domain="ex.com",
        configured_ips=["A", "B"], healthy_addresses={"A", "B"},
        users_by_ip={"A": 20, "B": 10}, node_by_ip={},
    )
    assert r == {"A", "B"}, "Cycle 1: both active"

    # Cycle 2: A overloaded
    r = svc._apply_capacity_filtering(
        zone_name="s1", domain="ex.com",
        configured_ips=["A", "B"], healthy_addresses={"A", "B"},
        users_by_ip={"A": 60, "B": 10}, node_by_ip={},
    )
    assert "A" not in r and "B" in r, "Cycle 2: A throttled"

    # Cycle 3: A drops to 40 (between thresholds) — stays removed
    r = svc._apply_capacity_filtering(
        zone_name="s1", domain="ex.com",
        configured_ips=["A", "B"], healthy_addresses={"A", "B"},
        users_by_ip={"A": 40, "B": 10}, node_by_ip={},
    )
    assert "A" not in r, "Cycle 3: A still removed (hysteresis)"

    # Cycle 4: A drops to 25 (below recover) — restored
    r = svc._apply_capacity_filtering(
        zone_name="s1", domain="ex.com",
        configured_ips=["A", "B"], healthy_addresses={"A", "B"},
        users_by_ip={"A": 25, "B": 10}, node_by_ip={},
    )
    assert r == {"A", "B"}, "Cycle 4: A restored"
    assert len(svc._overloaded_ips) == 0

    print("✅ Test 12: Full lifecycle (normal → throttle → hysteresis → recover)")


# ─────────────────────────────────────────────
#  Test 13: BUG CHECK — IPs from other zones in healthy_addresses
#  The effective set starts from ALL healthy_addresses, not zone-specific.
#  This means IPs from other zones pass through unfiltered. Is this correct?
# ─────────────────────────────────────────────
def test_cross_zone_healthy_addresses():
    """Verify that IPs belonging to other zones aren't accidentally removed."""
    svc = make_service(FakeConfig(max_users=50, recover_users=30))

    # Zone s1 has IPs A and B. But healthy_addresses includes C (from zone s2).
    r = svc._apply_capacity_filtering(
        zone_name="s1", domain="ex.com",
        configured_ips=["A", "B"],
        healthy_addresses={"A", "B", "C"},  # C is from another zone
        users_by_ip={"A": 60, "B": 10, "C": 40},
        node_by_ip={},
    )
    assert "C" in r, "IP from other zone should pass through untouched"
    assert "A" not in r, "Overloaded IP in this zone should be removed"
    assert "B" in r
    print("✅ Test 13: Cross-zone IPs pass through correctly")


# ─────────────────────────────────────────────
#  Test 14: Overloaded node goes unhealthy, comes back healthy
#           with users between thresholds → should stay removed
# ─────────────────────────────────────────────
def test_unhealthy_then_healthy_between_thresholds():
    svc = make_service(FakeConfig(max_users=50, recover_users=30))

    # Cycle 1: Node overloaded → throttled
    svc._apply_capacity_filtering(
        zone_name="s1", domain="ex.com",
        configured_ips=["A", "B"], healthy_addresses={"A", "B"},
        users_by_ip={"A": 60, "B": 10}, node_by_ip={},
    )
    assert "A" in svc._overloaded_ips

    # Cycle 2: Node A goes unhealthy (not in healthy_addresses)
    r = svc._apply_capacity_filtering(
        zone_name="s1", domain="ex.com",
        configured_ips=["A", "B"], healthy_addresses={"B"},
        users_by_ip={"B": 10}, node_by_ip={},
    )
    assert "A" in svc._overloaded_ips, "Should remain tracked while unhealthy"

    # Cycle 3: Node A comes back healthy with 40 users (between thresholds)
    r = svc._apply_capacity_filtering(
        zone_name="s1", domain="ex.com",
        configured_ips=["A", "B"], healthy_addresses={"A", "B"},
        users_by_ip={"A": 40, "B": 10}, node_by_ip={},
    )
    assert "A" not in r, "Should stay removed (between thresholds)"
    assert "A" in svc._overloaded_ips
    print("✅ Test 14: Unhealthy→healthy between thresholds — stays removed")


# ─────────────────────────────────────────────
#  Test 15: Stale entry — IP removed from config while overloaded
# ─────────────────────────────────────────────
def test_stale_overloaded_ip():
    svc = make_service(FakeConfig(max_users=50, recover_users=30))

    svc._overloaded_ips.add("REMOVED_IP")

    # REMOVED_IP is no longer in configured_ips
    r = svc._apply_capacity_filtering(
        zone_name="s1", domain="ex.com",
        configured_ips=["A", "B"], healthy_addresses={"A", "B"},
        users_by_ip={"A": 10, "B": 10}, node_by_ip={},
    )
    assert r == {"A", "B"}, "Stale IP should not affect results"
    # Stale entry remains in _overloaded_ips but is harmless
    assert "REMOVED_IP" in svc._overloaded_ips, "Stale entry stays (harmless)"
    print("✅ Test 15: Stale overloaded IP — harmless")


# ─────────────────────────────────────────────
#  Run all tests
# ─────────────────────────────────────────────
if __name__ == "__main__":
    test_lb_disabled_passthrough()
    test_normal_load_no_filtering()
    test_overloaded_node_throttled()
    test_hysteresis_between_thresholds()
    test_recovery_below_threshold()
    test_min_active_nodes()
    test_min_active_nodes_two()
    test_overloaded_ip_different_zone()
    test_unhealthy_overloaded_node()
    test_exact_boundary_max()
    test_exact_boundary_recover()
    test_full_lifecycle()
    test_cross_zone_healthy_addresses()
    test_unhealthy_then_healthy_between_thresholds()
    test_stale_overloaded_ip()
    print("\n🎉 All 15 tests passed!")
