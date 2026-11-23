"""Local OCI rehearsal using the existing AWS tally and a synthetic alert."""
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import sys

OCI = Path(__file__).resolve().parent
AWS = OCI.parent / "aws"
sys.path.insert(0, str(AWS))
import test_tally

spec = importlib.util.spec_from_file_location("oci_functions", OCI / "functions/main.py")
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
        event = json.loads((OCI / "fixtures/fallback-event.json").read_text(encoding="utf-8"))
        stored = {}
        client = Mock()

        class PreconditionFailed(Exception):
            status = 412

        def put(*args, **conditions):
            if "if_none_match" in conditions:
                self.assertEqual(conditions["if_none_match"], "*")
                if stored:
                    raise PreconditionFailed()
                stored.update(json.loads(args[-1]))
                return SimpleNamespace(headers={"etag": "pending"})
            self.assertEqual(conditions, {"if_match": "pending"})
            if client.put_object.call_count == 3:
                raise OSError("Object Storage unavailable after acknowledged delivery")
            stored.update(json.loads(args[-1]))

        client.put_object.side_effect = put
        client.get_object.side_effect = lambda *args: SimpleNamespace(
            data=SimpleNamespace(json=lambda: dict(stored)), headers={"etag": "pending"},
        )
        store = functions.EventStore(client, "namespace", "bucket")
        delivered = set()

        def provider(payload):
            self.assertEqual(payload, event)
            if sender.call_count == 1:
                raise TimeoutError("provider unavailable")
            delivered.add(payload["event_id"])

        with (patch.dict(sys.modules, {"oci.exceptions": SimpleNamespace(ServiceError=PreconditionFailed)}),
              patch.object(functions, "event_store", return_value=store),
              patch.object(functions, "send_notification", side_effect=provider) as sender):
            for status in (503, 503, 200, 200):
                self.assertEqual(functions.fallback_notification("POST", {**event, "summary": "ignored"})[1], status)
            self.assertEqual(stored["delivery_state"], "delivered")
            self.assertEqual(client.put_object.call_args.args[:3],
                             ("namespace", "bucket", "event-" + event["event_id"] + ".json"))
            self.assertEqual(functions.fallback_notification("POST", {**event, "status": "resolved"})[1], 409)
            self.assertEqual(functions.fallback_notification("POST", {**event, "ballot": "invalid"})[1], 400)
            self.assertEqual(sender.call_count, 3)
        self.assertEqual(delivered, {event["event_id"]})

    def test_gateway_auth_and_ops_payload(self):
        fixture = OCI.parent / "ops" / "fixtures" / "worker_unhealthy.json"
        event = json.loads(fixture.read_text(encoding="utf-8"))
        body = json.dumps(event).encode()
        with (patch.dict(functions.os.environ, {"RECOVERY_MODE": "fallback"}),
              patch.object(functions, "read_secret", return_value="fixture-secret"),
              patch.object(functions, "event_store") as factory):
            self.assertEqual(functions.dispatch("POST", {}, body)[1], 401)
            self.assertEqual(functions.dispatch("POST", {"authorization": "Bearer wrong"}, body)[1], 403)
            factory.assert_not_called()
            factory.return_value.process.return_value = "delivered"
            self.assertEqual(functions.dispatch("POST", {"authorization": ["Bearer fixture-secret"]}, body),
                             ({"status": "delivered"}, 200))
            factory.return_value.process.assert_called_once_with({key: event[key] for key in functions.REQUIRED})

    def test_supplemental_health(self):
        with patch.dict(functions.os.environ, {"PRIMARY_HEALTH_URL": "https://health.example.invalid"}):
            with patch.object(functions, "urlopen") as probe:
                probe.return_value.__enter__.return_value.status = 204
                self.assertEqual(functions.supplemental_health("GET")[1], 200)
                probe.side_effect = TimeoutError()
                self.assertEqual(functions.supplemental_health("GET")[1], 503)


if __name__ == "__main__":
    unittest.main(verbosity=2)
