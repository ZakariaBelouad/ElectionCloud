"""Exercise the existing Cosmos tally logic with synthetic in-memory storage."""
import base64
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cosmos_store import CosmosStore
from electioncloud import encrypt_ballot, new_keypair
from tally_result import aggregate


class TallyTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        public, private = new_keypair()
        self.key = Path(temp.name) / "synthetic.pem"
        self.key.write_bytes(private)
        self.container = Mock()
        self.store = CosmosStore(self.container, "synthetic-aws-001")
        self.state = {
            "publicKey": public.decode(), "closed": False, "accepted": 1,
            "candidates": ["Candidate A", "Candidate B"],
        }
        self.container.read_item.return_value = self.state
        self.container.query_items.return_value = [{
            "id": "ballot-" + "a" * 32,
            "ciphertext": base64.b64encode(encrypt_ballot(public, 1)).decode(),
        }]

    def tally(self, key):
        return self.store.run(SimpleNamespace(command="tally", private_key=key))

    def test_topic_contract(self):
        self.assertEqual(self.store.topic(), "electioncloud-" +
                         hashlib.sha256(self.state["publicKey"].encode()).hexdigest()[:32])

    def test_before_closure(self):
        with self.assertRaisesRegex(ValueError, "Close the election"):
            self.tally(self.key)
        self.container.query_items.assert_not_called()

    def test_missing_and_wrong_key(self):
        self.state["closed"] = True
        wrong = self.key.with_name("wrong.pem")
        wrong.write_bytes(new_keypair()[1])
        with self.assertRaises(FileNotFoundError):
            self.tally(self.key.with_name("missing.pem"))
        with self.assertRaisesRegex(ValueError, "key"):
            self.tally(wrong)
        self.container.query_items.assert_not_called()

    def test_one_counted_vote(self):
        self.state["closed"] = True
        fixture = json.loads(Path(__file__).with_name("result-fixture.json").read_text())
        result = aggregate(self.store.election, self.tally(self.key))
        self.assertEqual(json.loads(json.dumps(result)), fixture)
        self.assertEqual(self.container.query_items.call_args.kwargs["partition_key"],
                         self.store.election)
        self.container.execute_item_batch.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
