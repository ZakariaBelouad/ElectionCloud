"""Cosmos DB storage for a single-partition academic election."""

import base64
import hashlib
import os
import secrets

from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosBatchOperationError, CosmosHttpResponseError
from azure.core.exceptions import AzureError
from azure.identity import AzureCliCredential, ManagedIdentityCredential
from cryptography.hazmat.primitives import serialization

from electioncloud import (
    StorageUnavailable,
    count_ballots,
    encrypt_ballot,
    new_keypair,
    public_pem,
    receipt_id,
    validate_candidates,
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def replace(document, **changes):
    body = {key: value for key, value in document.items() if not key.startswith("_")}
    body.update(changes)
    return "replace", (document["id"], body), {"if_match_etag": document["_etag"]}


class CosmosStore:
    def __init__(self, container, election):
        self.container = container
        self.election = election

    @classmethod
    def from_environment(cls):
        names = ("COSMOS_ENDPOINT", "COSMOS_DATABASE", "COSMOS_CONTAINER",
                 "ELECTIONCLOUD_ELECTION_ID")
        missing = [name for name in names if not os.environ.get(name)]
        if missing:
            raise ValueError("Missing Cosmos settings: " + ", ".join(missing))
        endpoint, database, container, election = (os.environ[name] for name in names)
        authentication = os.environ.get("COSMOS_AUTH", "key")
        if authentication == "managed-identity":
            client_id = os.environ.get("AZURE_CLIENT_ID")
            credential = ManagedIdentityCredential(client_id=client_id) if client_id else ManagedIdentityCredential()
        elif authentication == "azure-cli":
            credential = AzureCliCredential()
        elif authentication == "key" and os.environ.get("COSMOS_KEY"):
            credential = os.environ["COSMOS_KEY"]
        else:
            raise ValueError("Choose Cosmos managed-identity or azure-cli auth, or provide COSMOS_KEY for key auth.")
        client = CosmosClient(endpoint, credential=credential, connection_timeout=5, retry_total=4)
        return cls(client.get_database_client(database).get_container_client(container), election)

    def document(self, identifier, kind, **fields):
        return {"id": identifier, "electionId": self.election, "kind": kind, **fields}

    def read(self, identifier):
        try:
            return self.container.read_item(identifier, partition_key=self.election)
        except CosmosHttpResponseError as error:
            if error.status_code == 404:
                return None
            raise StorageUnavailable(f"Cosmos read failed (HTTP {error.status_code}).") from error
        except AzureError as error:
            raise StorageUnavailable("Cosmos read failed.") from error

    def batch(self, *operations):
        try:
            self.container.execute_item_batch(operations, partition_key=self.election)
            return True
        except CosmosBatchOperationError as error:
            status = error.operation_responses[error.error_index]["statusCode"]
            if status in {404, 409, 412}:
                return False
            raise StorageUnavailable(f"Cosmos transaction failed (HTTP {status}).") from error
        except AzureError as error:
            raise StorageUnavailable("Cosmos transaction failed.") from error

    def initialize(self, args):
        validate_candidates(args.candidates)
        if args.private_key.exists():
            private_key = serialization.load_pem_private_key(args.private_key.read_bytes(), None)
            public_bytes = public_pem(private_key)
        else:
            public_bytes, private_bytes = new_keypair()
            # Preserve the key if the remote write succeeds but its response is lost.
            descriptor = os.open(args.private_key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as target:
                target.write(private_bytes)
                target.flush()
                os.fsync(target.fileno())
        state = self.document("state", "state", publicKey=public_bytes.decode(),
                              candidates=args.candidates, closed=False, pending=0, accepted=0)
        if self.batch(("create", (state,))):
            return "Election initialized."
        existing = self.read("state")
        if existing and existing["publicKey"] == state["publicKey"] and existing["candidates"] == args.candidates:
            return "Election already initialized with this key."
        raise ValueError("This election ID already exists. Choose a new election ID and tally key.")

    def receipt(self, ballot_id):
        if self.read("ballot-" + ballot_id):
            status = "accepted"
        elif self.read("outbox-" + ballot_id):
            status = "pending"
        else:
            # The worker can move the outbox entry between the first two reads.
            status = "accepted" if self.read("ballot-" + ballot_id) else "unknown"
        return {"status": status, "ballot_id": ballot_id}

    def state(self):
        state = self.read("state")
        if state is None:
            raise ValueError("Initialize this Cosmos election first.")
        return state

    def run(self, args):
        command = args.command
        if command == "receipt":
            return self.receipt(receipt_id(args.session))
        for _ in range(8):
            state = self.state()
            candidates = dict(enumerate(state["candidates"], 1))
            if command == "candidates":
                return candidates
            if command == "turnout":
                return {"accepted_ballots": state["accepted"], "closed": state["closed"]}
            if command == "tally":
                if not state["closed"]:
                    raise ValueError("Close the election before counting ballots.")
                ciphertexts = (base64.b64decode(item["ciphertext"]) for item in self.query("ballot"))
                counts = count_ballots(candidates, ciphertexts, args.private_key, state["publicKey"].encode())
                if sum(counts.values()) != state["accepted"]:
                    raise StorageUnavailable("The tally could not read every accepted ballot. Retry.")
                return counts
            if command == "close":
                if state["closed"]:
                    return "Election closed."
                if state["pending"]:
                    raise ValueError("Wait for the Kafka worker to store queued ballots before closing.")
                if self.batch(replace(state, closed=True)):
                    return "Election closed."
                continue
            if command == "issue":
                if state["closed"]:
                    raise ValueError("The election is closed.")
                voter_id = "voter-" + digest(args.voter_reference)
                if self.read(voter_id):
                    raise ValueError("This voter already has a session or has voted.")
                token = secrets.token_urlsafe(32)
                voter = self.document(voter_id, "voter")
                session = self.document("session-" + digest(token), "session")
                if self.batch(replace(state), ("create", (voter,)), ("create", (session,))):
                    return token
                continue
            if command not in {"vote", "queue_vote"}:
                raise ValueError(f"Unsupported election command: {command}")
            streaming = command == "queue_vote"
            ballot_id = receipt_id(args.session) if streaming else secrets.token_hex(16)
            if streaming:
                previous = self.receipt(ballot_id)
                if previous["status"] != "unknown":
                    return previous
            if state["closed"]:
                raise ValueError("The election is closed.")
            if args.candidate not in candidates:
                raise ValueError("Unknown candidate ID.")
            session = self.read("session-" + digest(args.session))
            if session is None:
                if streaming:
                    previous = self.receipt(ballot_id)
                    if previous["status"] != "unknown":
                        return previous
                raise ValueError("Invalid or already used session.")
            ciphertext = base64.b64encode(encrypt_ballot(state["publicKey"].encode(), args.candidate)).decode()
            kind = "outbox" if streaming else "ballot"
            record = self.document(kind + "-" + ballot_id, kind, ciphertext=ciphertext)
            counter = "pending" if streaming else "accepted"
            if self.batch(replace(state, **{counter: state[counter] + 1}),
                          ("delete", (session["id"],), {"if_match_etag": session["_etag"]}),
                          ("create", (record,))):
                return {"status": "pending" if streaming else "accepted", "ballot_id": ballot_id}
        raise StorageUnavailable("The election is busy. Retry with the same session token.")

    def query(self, kind, limit=None):
        query = "SELECT TOP 100 c.id, c.ciphertext" if limit else "SELECT c.id, c.ciphertext"
        try:
            yield from self.container.query_items(
                query + " FROM c WHERE c.kind = @kind",
                parameters=[{"name": "@kind", "value": kind}],
                partition_key=self.election,
            )
        except AzureError as error:
            raise StorageUnavailable("Cosmos query failed.") from error

    def topic(self):
        return "electioncloud-" + digest(self.state()["publicKey"])[:32]

    def pending_ballots(self):
        return [(item["id"].removeprefix("outbox-"), base64.b64decode(item["ciphertext"]))
                for item in self.query("outbox", limit=100)]

    def store_ballot(self, key, ciphertext):
        if key is None or len(key) != 32 or ciphertext is None:
            return False
        ballot_id = key.decode("ascii", errors="replace")
        if any(character not in "0123456789abcdef" for character in ballot_id):
            return False
        encoded = base64.b64encode(ciphertext).decode()
        for _ in range(8):
            state = self.state()
            pending = self.read("outbox-" + ballot_id)
            if pending is None or pending["ciphertext"] != encoded:
                return False
            ballot = self.document("ballot-" + ballot_id, "ballot", ciphertext=encoded)
            if self.batch(replace(state, pending=state["pending"] - 1, accepted=state["accepted"] + 1),
                          ("delete", (pending["id"],), {"if_match_etag": pending["_etag"]}),
                          ("create", (ballot,))):
                return True
        raise StorageUnavailable("Cosmos could not commit the ballot. Restart the worker to retry.")
