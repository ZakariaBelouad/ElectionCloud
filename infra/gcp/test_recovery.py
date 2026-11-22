"""Local GCP rehearsal using the existing AWS tally and a synthetic alert."""
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import sys

GCP = Path(__file__).resolve().parent
AWS = GCP.parent / "aws"
sys.path.insert(0, str(AWS))
import test_tally

spec = importlib.util.spec_from_file_location("gcp_functions", GCP / "functions/main.py")
functions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(functions)


class RecoveryTest(unittest.TestCase):
    def test_switch_to_standby(self):
        start = perf_counter()
        fixture = test_tally.TallyTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.state["closed"] = True
        # The EC2 host is simulated as unavailable. Its approved reference is
        # the committed result for this same synthetic election.
        primary = json.loads((AWS / "result-fixture.json").read_text(encoding="utf-8"))
        standby = test_tally.aggregate(fixture.store.election, fixture.tally(fixture.key))
        self.assertEqual(standby, primary)
        self.assertEqual(standby["totalCounted"], fixture.state["accepted"])

        # Exclusive create is the local equivalent of the shared conditional create.
        with TemporaryDirectory() as temporary:
            canonical = Path(temporary) / (standby["electionId"] + ".json")
            with canonical.open("x", encoding="utf-8") as result:
                json.dump(standby, result)
            with self.assertRaises(FileExistsError):
                with canonical.open("x", encoding="utf-8"):
                    pass
            self.assertEqual(json.loads(canonical.read_text(encoding="utf-8")), primary)
        print(f"Synthetic standby tally and publication guard: {perf_counter() - start:.3f}s")

    def test_fallback_replay_and_storage_failure(self):
        event = json.loads((GCP / "fixtures/fallback-event.json").read_text(encoding="utf-8"))
        request = SimpleNamespace(method="POST", get_json=lambda **_: event)
        from google.api_core.exceptions import AlreadyExists

        document = Mock()
        document.create.side_effect = [OSError("unavailable"), None, AlreadyExists("replay"),
                                       AlreadyExists("id collision")]
        document.get.return_value.to_dict.return_value = event
        client = Mock()
        client.collection.return_value.document.return_value = document

        with (patch("google.cloud.firestore.Client", return_value=client),
              patch.object(functions, "deliver", side_effect=["delivered", "duplicate"]) as deliver):
            for status in (503, 200, 200):
                self.assertEqual(functions.fallback_notification(request)[1], status)
            self.assertEqual(document.create.call_args_list[1].args[0]["event_id"], event["event_id"])
            self.assertEqual(document.create.call_args_list[1].args[0]["delivery_state"], "pending")
            client.collection.return_value.document.assert_called_with("event-" + event["event_id"])
            request.get_json = lambda **_: {**event, "status": "resolved"}
            self.assertEqual(functions.fallback_notification(request)[1], 409)
            request.get_json = lambda **_: {**event, "ballot": "unknown untrusted field"}
            self.assertEqual(functions.fallback_notification(request)[1], 400)
            self.assertEqual(deliver.call_count, 2)
        self.assertEqual(document.create.call_count, 4)

    def test_delivery_failure_and_ambiguous_acknowledgement(self):
        event = json.loads((GCP / "fixtures/fallback-event.json").read_text(encoding="utf-8"))
        request = SimpleNamespace(method="POST", get_json=lambda **_: {**event, "summary": "ignored"})
        record = {**event, "delivery_state": "pending"}
        document = Mock()
        document.get.return_value.exists = True
        document.get.return_value.to_dict.return_value = record

        def acknowledge(update):
            record.update(update)

        document.update.side_effect = [OSError("Firestore unavailable"), None]

        # The fake provider models the required provider-side idempotency contract.
        delivered = set()

        def provider(payload):
            if sender.call_count == 1:
                raise TimeoutError("provider unavailable")
            delivered.add(payload["event_id"])

        with patch("google.cloud.firestore.Client") as client:
            client.return_value.collection.return_value.document.return_value = document
            with (patch.object(functions, "enqueue", return_value="duplicate") as enqueue,
                  patch.object(functions, "send_notification", side_effect=provider) as sender):
                self.assertEqual(functions.fallback_notification(request)[1], 503)
                document.update.assert_not_called()
                self.assertEqual(functions.fallback_notification(request)[1], 503)
                self.assertEqual(record["delivery_state"], "pending")
                document.update.side_effect = acknowledge
                self.assertEqual(functions.fallback_notification(request), ({"status": "delivered"}, 200))
                self.assertEqual(functions.fallback_notification(request), ({"status": "duplicate"}, 200))
                self.assertEqual(sender.call_count, 3)
                enqueue.assert_called_with(event)
        self.assertEqual(delivered, {event["event_id"]})

    def test_ops_router_payload(self):
        fixture = GCP.parent / "ops" / "fixtures" / "worker_unhealthy.json"
        event = json.loads(fixture.read_text(encoding="utf-8"))
        request = SimpleNamespace(method="POST", get_json=lambda **_: event)
        with (patch.object(functions, "enqueue", return_value="queued") as enqueue,
              patch.object(functions, "deliver", return_value="delivered")):
            self.assertEqual(functions.fallback_notification(request),
                             ({"status": "delivered"}, 200))
        enqueue.assert_called_once_with({key: event[key] for key in functions.REQUIRED})

    def test_supplemental_health(self):
        request = SimpleNamespace(method="GET")
        with patch.dict(functions.os.environ, {"PRIMARY_HEALTH_URL": "https://health.example.invalid"}):
            with patch.object(functions, "urlopen") as probe:
                probe.return_value.__enter__.return_value.status = 204
                self.assertEqual(functions.supplemental_health(request)[1], 200)
                probe.side_effect = TimeoutError()
                self.assertEqual(functions.supplemental_health(request)[1], 503)


if __name__ == "__main__":
    unittest.main(verbosity=2)
