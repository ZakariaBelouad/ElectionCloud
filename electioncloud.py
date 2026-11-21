import argparse
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

SCHEMA = """
CREATE TABLE election (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    public_key BLOB NOT NULL,
    closed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE candidates (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE voters (
    reference TEXT PRIMARY KEY,
    session_hash TEXT UNIQUE,
    voted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE ballots (id TEXT PRIMARY KEY, ciphertext BLOB NOT NULL);
"""

OUTBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS ballot_outbox (
    id TEXT PRIMARY KEY,
    ciphertext BLOB NOT NULL
)
"""


def ballot_padding():
    return padding.OAEP(
        mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None
    )


class StorageUnavailable(Exception):
    pass


def configured_storage():
    backend = os.environ.get("ELECTIONCLOUD_STORAGE", "sqlite")
    if backend == "sqlite":
        return None
    if backend != "cosmos":
        raise ValueError("ELECTIONCLOUD_STORAGE must be sqlite or cosmos.")
    try:
        from cosmos_store import CosmosStore
    except ImportError as error:
        raise ValueError("Install Cosmos storage support with requirements-cosmos.txt.") from error

    return CosmosStore.from_environment()


def receipt_id(session):
    return hmac.digest(session.encode(), b"ElectionCloud receipt v1", "sha256").hex()[:32]


def kafka_receipt(db, session):
    # Only someone holding the original random token can recover this receipt.
    ballot_id = receipt_id(session)
    if db.execute("SELECT 1 FROM ballots WHERE id = ?", (ballot_id,)).fetchone():
        return {"status": "accepted", "ballot_id": ballot_id}
    if db.execute("SELECT 1 FROM ballot_outbox WHERE id = ?", (ballot_id,)).fetchone():
        return {"status": "pending", "ballot_id": ballot_id}
    return {"status": "unknown", "ballot_id": ballot_id}


def validate_candidates(candidates):
    if len(set(candidates)) < 2 or len(set(candidates)) != len(candidates):
        raise ValueError("Supply at least two distinct candidate names.")


def public_pem(private_key):
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def new_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    return public_pem(private_key), private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def encrypt_ballot(public_bytes, candidate):
    public_key = serialization.load_pem_public_key(public_bytes)
    return public_key.encrypt(str(candidate).encode(), ballot_padding())


def count_ballots(candidates, ciphertexts, key_path, public_bytes):
    private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if public_pem(private_key) != public_bytes:
        raise ValueError("This key belongs to a different election.")
    counts = dict.fromkeys(candidates.values(), 0)
    for ciphertext in ciphertexts:
        candidate_id = int(private_key.decrypt(ciphertext, ballot_padding()))
        counts[candidates[candidate_id]] += 1
    return counts


def initialize(args):
    validate_candidates(args.candidates)
    public_bytes, private_bytes = new_keypair()
    with args.db.open("xb"):
        pass
    key_written = False
    try:
        with args.private_key.open("xb") as key_file:
            key_written = True
            key_file.write(private_bytes)
        with closing(sqlite3.connect(args.db)) as db, db:
            db.executescript(SCHEMA)
            db.execute("INSERT INTO election (id, public_key) VALUES (1, ?)", (public_bytes,))
            db.executemany("INSERT INTO candidates (name) VALUES (?)",
                           [(name,) for name in args.candidates])
    except Exception:
        args.db.unlink()
        if key_written:
            args.private_key.unlink()
        raise
    return "Election initialized."


def run(db, args):
    public_bytes, closed = db.execute(
        "SELECT public_key, closed FROM election WHERE id = 1"
    ).fetchone()

    if args.command == "candidates":
        return dict(db.execute("SELECT id, name FROM candidates ORDER BY id"))
    if args.command == "turnout":
        count = db.execute("SELECT COUNT(*) FROM ballots").fetchone()[0]
        return {"accepted_ballots": count, "closed": bool(closed)}
    if args.command == "close":
        db.execute(OUTBOX_SCHEMA)
        if db.execute("SELECT 1 FROM ballot_outbox LIMIT 1").fetchone():
            raise ValueError("Wait for the Kafka worker to store queued ballots before closing.")
        db.execute("UPDATE election SET closed = 1 WHERE id = 1")
        return "Election closed."
    if args.command == "tally":
        if not closed:
            raise ValueError("Close the election before counting ballots.")
        candidates = dict(db.execute("SELECT id, name FROM candidates ORDER BY id"))
        ciphertexts = (row[0] for row in db.execute("SELECT ciphertext FROM ballots"))
        return count_ballots(candidates, ciphertexts, args.private_key, public_bytes)

    streaming = args.command == "queue_vote"
    if streaming or args.command == "receipt":
        db.execute(OUTBOX_SCHEMA)
        receipt = kafka_receipt(db, args.session)
        if args.command == "receipt" or receipt["status"] != "unknown":
            return receipt

    if closed:
        raise ValueError("The election is closed.")
    if args.command == "issue":
        token = secrets.token_urlsafe(32)
        cursor = db.execute(
            """INSERT INTO voters (reference, session_hash) VALUES (?, ?)
               ON CONFLICT(reference) DO UPDATE SET session_hash = excluded.session_hash
               WHERE voters.voted = 0 AND voters.session_hash IS NULL""",
            (args.voter_reference, hashlib.sha256(token.encode()).hexdigest()),
        )
        if cursor.rowcount != 1:
            raise ValueError("This voter already has a session or has voted.")
        return token

    if not db.execute("SELECT 1 FROM candidates WHERE id = ?", (args.candidate,)).fetchone():
        raise ValueError("Unknown candidate ID.")
    cursor = db.execute(
        "UPDATE voters SET session_hash = NULL, voted = 1 WHERE session_hash = ? AND voted = 0",
        (hashlib.sha256(args.session.encode()).hexdigest(),),
    )
    if cursor.rowcount != 1:
        raise ValueError("Invalid or already used session.")
    ciphertext = encrypt_ballot(public_bytes, args.candidate)
    if streaming:
        ballot_id = receipt["ballot_id"]
        db.execute("INSERT INTO ballot_outbox VALUES (?, ?)", (ballot_id, ciphertext))
        return {"status": "pending", "ballot_id": ballot_id}
    ballot_id = secrets.token_hex(16)
    db.execute("INSERT INTO ballots VALUES (?, ?)", (ballot_id, ciphertext))
    return {"status": "accepted", "ballot_id": ballot_id}


def transaction(path, operation, *args):
    uri = path.resolve().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        return operation(db, *args)


def execute(args):
    return transaction(args.db, run, args)


def main():
    parser = argparse.ArgumentParser(description="ElectionCloud local academic prototype")
    parser.add_argument("--db", type=Path, default=Path("election.db"))
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--private-key", type=Path, required=True)
    init.add_argument("candidates", nargs="+")
    commands.add_parser("candidates")
    issue = commands.add_parser("issue")
    issue.add_argument("voter_reference")
    vote = commands.add_parser("vote")
    vote.add_argument("candidate", type=int)
    commands.add_parser("turnout")
    commands.add_parser("close")
    tally = commands.add_parser("tally")
    tally.add_argument("--private-key", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "vote":
        args.session = input("Session token: ").strip()

    try:
        storage = configured_storage()
        if args.command == "init":
            result = storage.initialize(args) if storage else initialize(args)
        else:
            result = storage.run(args) if storage else execute(args)
    except FileExistsError as error:
        parser.exit(
            1, f"ElectionCloud: {error.filename} already exists. "
            "To start a separate election, choose unused paths for --db and --private-key.\n"
        )
    except (OSError, sqlite3.Error, StorageUnavailable, ValueError) as error:
        parser.exit(1, f"ElectionCloud: {error}\n")

    print(json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else result)


if __name__ == "__main__":
    main()
