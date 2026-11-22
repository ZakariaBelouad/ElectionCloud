"""Alert routing tests. Pure Python: no AWS, no network, no real notifications."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infra" / "ops" / "lambda"))

import alert_handler as alerts  # noqa: E402

FIXTURES = ROOT / "infra" / "ops" / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def quiet(_line):
    pass


class ValidationTests(unittest.TestCase):
    def test_all_valid_fixtures_pass(self):
        for name in ("worker_unhealthy", "kafka_unavailable", "cosmos_write_failures", "recovery"):
            with self.subTest(name):
                self.assertEqual(alerts.validate(fixture(name + ".json"))["event_id"], fixture(name + ".json")["event_id"])

    def test_voter_field_is_rejected(self):
        with self.assertRaises(alerts.InvalidEvent):
            alerts.validate(fixture("invalid_voter_field.json"))

    def test_secret_looking_summary_is_rejected(self):
        with self.assertRaises(alerts.InvalidEvent):
            alerts.validate(fixture("invalid_token_in_summary.json"))

    def test_long_random_string_in_summary_is_rejected(self):
        event = fixture("worker_unhealthy.json")
        event["summary"] = "see " + "a1B2c3D4" * 5
        with self.assertRaises(alerts.InvalidEvent):
            alerts.validate(event)

    def test_bad_enum_and_time_are_rejected(self):
        for field, value in (("service", "voting-db"), ("severity", "panic"), ("status", "maybe"),
                             ("observed_at", "yesterday"), ("observed_at", "2026-11-21T10:00:00+02:00"),
                             ("observed_at", "2026-11-21T10:00:00")):
            event = fixture("worker_unhealthy.json")
            event[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(alerts.InvalidEvent):
                alerts.validate(event)

    def test_missing_field_is_rejected(self):
        event = fixture("worker_unhealthy.json")
        del event["status"]
        with self.assertRaises(alerts.InvalidEvent):
            alerts.validate(event)


class AlarmMappingTests(unittest.TestCase):
    def test_alarm_becomes_valid_event(self):
        event = alerts.from_alarm(fixture("alarm_state_change.json")["detail"])
        self.assertEqual(alerts.validate(event), event)
        self.assertEqual((event["service"], event["severity"], event["status"]), ("kafka", "critical", "firing"))

    def test_same_alarm_transition_gets_same_id(self):
        detail = fixture("alarm_state_change.json")["detail"]
        self.assertEqual(alerts.from_alarm(detail)["event_id"], alerts.from_alarm(detail)["event_id"])

    def test_ok_state_is_resolved(self):
        detail = fixture("alarm_state_change.json")["detail"]
        detail["state"]["value"] = "OK"
        event = alerts.from_alarm(detail)
        self.assertEqual((event["severity"], event["status"]), ("info", "resolved"))


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.dedup = alerts.MemoryDedup()
        self.primary = alerts.MockSender("primary")
        self.fallback = alerts.MockSender("fallback")

    def route(self, name="worker_unhealthy.json"):
        return alerts.route(fixture(name), self.dedup, self.primary, self.fallback, log=quiet)

    def test_event_is_delivered_once(self):
        self.assertEqual(self.route()["route"], "primary")
        self.assertEqual(len(self.primary.sent), 1)

    def test_repeated_event_is_sent_only_once(self):
        results = [self.route()["result"] for _ in range(5)]
        self.assertEqual(results, ["sent", "duplicate", "duplicate", "duplicate", "duplicate"])
        self.assertEqual(len(self.primary.sent), 1)
        self.assertEqual(self.fallback.sent, [])

    def test_different_events_are_each_delivered(self):
        for name in ("worker_unhealthy.json", "kafka_unavailable.json", "cosmos_write_failures.json", "recovery.json"):
            self.route(name)
        self.assertEqual(len(self.primary.sent), 4)

    def test_dedup_entry_expires(self):
        now = [1000.0]
        self.dedup = alerts.MemoryDedup(clock=lambda: now[0])
        self.route()
        now[0] += alerts.DEDUP_TTL_SECONDS + 1
        self.assertEqual(self.route()["result"], "sent")

    def test_primary_failure_uses_fallback(self):
        self.primary.fail = True
        self.assertEqual(self.route()["route"], "fallback")
        self.assertEqual(len(self.fallback.sent), 1)

    def test_total_failure_raises_and_allows_retry(self):
        self.primary.fail = self.fallback.fail = True
        with self.assertRaises(alerts.NotificationFailed):
            self.route()
        self.primary.fail = False  # destination comes back; the retry must not be treated as a duplicate
        self.assertEqual(self.route()["result"], "sent")
        self.assertEqual(len(self.primary.sent), 1)

    def test_no_fallback_configured_still_fails_cleanly(self):
        self.primary.fail = True
        with self.assertRaises(alerts.NotificationFailed):
            alerts.route(fixture("worker_unhealthy.json"), self.dedup, self.primary, None, log=quiet)

    def test_invalid_event_never_reaches_a_sender(self):
        with self.assertRaises(alerts.InvalidEvent):
            self.route("invalid_voter_field.json")
        self.assertEqual(self.primary.sent + self.fallback.sent, [])


class PrivacyTests(unittest.TestCase):
    def test_messages_and_logs_contain_technical_status_only(self):
        lines, sender = [], alerts.MockSender()
        alerts.route(fixture("kafka_unavailable.json"), alerts.MemoryDedup(), sender, log=lines.append)
        text = json.dumps(sender.sent) + "\n".join(lines)
        for forbidden in ("voter", "ballot", "candidate", "token", "password", "BEGIN"):
            self.assertNotIn(forbidden, text.lower() if forbidden != "BEGIN" else text)

    def test_fallback_requires_https(self):
        with self.assertRaises(ValueError):
            alerts.HttpFallbackSender("http://example.test/hook")


class FakeSns:
    def __init__(self, fail=False):
        self.fail, self.published = fail, []

    def publish(self, **kwargs):
        if self.fail:
            raise RuntimeError("endpoint unavailable")
        self.published.append(kwargs)


class SnsSenderTests(unittest.TestCase):
    def test_publish_and_failure_mapping(self):
        client = FakeSns()
        alerts.SnsSender("arn:aws:sns:test:topic", client).send({}, {"subject": "s", "body": "b"})
        self.assertEqual(client.published[0]["Message"], "b")
        with self.assertRaises(alerts.NotificationFailed):
            alerts.SnsSender("arn:aws:sns:test:topic", FakeSns(fail=True)).send({}, {"subject": "s", "body": "b"})


if __name__ == "__main__":
    unittest.main()
