import hashlib
import hmac
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.observer.controller import ObserverController


class FakeConfig:
    def __init__(self, state_file: str, threshold: float = 0.5):
        self.observer_enabled = True
        self.observer_shadow_mode = False
        self.observer_shared_secret = "secret"
        self.observer_allowed_ids = ["mm-observer"]
        self.observer_freshness_ttl_seconds = 120
        self.observer_extended_stale_threshold_seconds = 300
        self.observer_mass_degradation_threshold_ratio = threshold
        self.observer_force_active_ips = []
        self.observer_force_drained_ips = []
        self.observer_state_file = state_file


def sign(secret: str, payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return body, signature


def snapshot(sequence: int, nodes: list[dict], issued_at: int | None = None, ttl: int = 120) -> dict:
    issued_at = issued_at or int(time.time())
    return {
        "version": 1,
        "observer_id": "mm-observer",
        "observer_scope": "mm",
        "sequence": sequence,
        "issued_at": issued_at,
        "expires_at": issued_at + ttl,
        "nodes": nodes,
    }


class ObserverControllerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.state_file = str(Path(self.tempdir.name) / "observer-state.json")
        self.controller = ObserverController(FakeConfig(self.state_file))

    def tearDown(self):
        self.tempdir.cleanup()

    def test_accepts_snapshot_and_evaluates_zone(self):
        payload = snapshot(
            sequence=1,
            nodes=[
                {
                    "ip": "1.1.1.1",
                    "node": "SG Node",
                    "desired_state": "drained",
                    "restore_candidate": False,
                    "reasons": ["offline"],
                },
                {
                    "ip": "2.2.2.2",
                    "node": "JP Node",
                    "desired_state": "healthy",
                    "restore_candidate": True,
                    "reasons": [],
                },
            ],
        )
        body, signature = sign("secret", payload)
        status, response = self.controller.handle_snapshot(body, signature)
        self.assertEqual(status, 202)
        self.assertTrue(response["ok"])

        decision = self.controller.evaluate_zone(
            observer_scope="mm",
            configured_ips=["1.1.1.1", "2.2.2.2"],
            base_eligible_ips={"1.1.1.1", "2.2.2.2"},
            min_active_nodes=1,
        )
        self.assertEqual(decision.effective_drained_ips, {"1.1.1.1"})
        self.assertEqual(decision.dns_eligible_ips, {"2.2.2.2"})
        self.assertEqual(decision.reasons_by_ip["1.1.1.1"], ["offline"])

    def test_rejects_replayed_sequence(self):
        payload = snapshot(sequence=1, nodes=[{"ip": "1.1.1.1", "node": "SG", "desired_state": "healthy"}])
        body, signature = sign("secret", payload)
        first_status, _ = self.controller.handle_snapshot(body, signature)
        second_status, response = self.controller.handle_snapshot(body, signature)
        self.assertEqual(first_status, 202)
        self.assertEqual(second_status, 400)
        self.assertIn("not newer", response["error"])

    def test_mass_freeze_keeps_existing_drains_only(self):
        controller = ObserverController(FakeConfig(self.state_file, threshold=0.4))

        first = snapshot(
            sequence=1,
            nodes=[
                {"ip": "1.1.1.1", "node": "SG", "desired_state": "drained", "reasons": ["offline"]},
                {"ip": "2.2.2.2", "node": "JP", "desired_state": "healthy"},
                {"ip": "3.3.3.3", "node": "KR", "desired_state": "healthy"},
                {"ip": "4.4.4.4", "node": "TH", "desired_state": "healthy"},
            ],
        )
        second = snapshot(
            sequence=2,
            nodes=[
                {"ip": "1.1.1.1", "node": "SG", "desired_state": "drained", "reasons": ["offline"]},
                {"ip": "2.2.2.2", "node": "JP", "desired_state": "drained", "reasons": ["throttled"]},
                {"ip": "3.3.3.3", "node": "KR", "desired_state": "drained", "reasons": ["throttled"]},
                {"ip": "4.4.4.4", "node": "TH", "desired_state": "healthy"},
            ],
        )

        for payload in (first, second):
            body, signature = sign("secret", payload)
            status, response = controller.handle_snapshot(body, signature)
            self.assertEqual(status, 202, response)

        decision = controller.evaluate_zone(
            observer_scope="mm",
            configured_ips=["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"],
            base_eligible_ips={"1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"},
            min_active_nodes=1,
        )
        self.assertTrue(decision.mass_freeze_active)
        self.assertEqual(decision.effective_drained_ips, {"1.1.1.1"})
        self.assertNotIn("2.2.2.2", decision.effective_drained_ips)

    def test_min_active_blocks_last_remaining_drain(self):
        controller = ObserverController(FakeConfig(self.state_file, threshold=1.0))
        payload = snapshot(
            sequence=1,
            nodes=[
                {"ip": "1.1.1.1", "node": "SG", "desired_state": "drained", "reasons": ["offline"]},
                {"ip": "2.2.2.2", "node": "JP", "desired_state": "drained", "reasons": ["throttled"]},
            ],
        )
        body, signature = sign("secret", payload)
        status, response = controller.handle_snapshot(body, signature)
        self.assertEqual(status, 202, response)

        decision = controller.evaluate_zone(
            observer_scope="mm",
            configured_ips=["1.1.1.1", "2.2.2.2"],
            base_eligible_ips={"1.1.1.1", "2.2.2.2"},
            min_active_nodes=1,
        )
        self.assertEqual(len(decision.effective_drained_ips), 1)
        self.assertEqual(len(decision.blocked_ips), 1)


if __name__ == "__main__":
    unittest.main()
