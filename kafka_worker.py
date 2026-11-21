"""Relay queued ballots through Kafka and commit them to the local ballot box."""

import argparse
import hashlib
import os
import sqlite3
import time
from functools import partial
from pathlib import Path

from electioncloud import OUTBOX_SCHEMA, StorageUnavailable, configured_storage, transaction


def election_topic(db):
    public_key, = db.execute("SELECT public_key FROM election WHERE id = 1").fetchone()
    db.execute(OUTBOX_SCHEMA)
    return "electioncloud-" + hashlib.sha256(public_key).hexdigest()[:32]


def pending_ballots(db):
    return db.execute("SELECT id, ciphertext FROM ballot_outbox ORDER BY rowid LIMIT 100").fetchall()


def store_ballot(db, key, ciphertext):
    # The durable outbox authorizes the exact ciphertext. Once removed, a replay is a no-op.
    if key is None or len(key) != 32 or ciphertext is None:
        return False
    ballot_id = key.decode("ascii", errors="replace")
    if not db.execute(
        "SELECT 1 FROM ballot_outbox WHERE id = ? AND ciphertext = ?",
        (ballot_id, ciphertext),
    ).fetchone():
        return False
    db.execute("INSERT INTO ballots VALUES (?, ?)", (ballot_id, ciphertext))
    db.execute("DELETE FROM ballot_outbox WHERE id = ?", (ballot_id,))
    return True


def relay(topic, producer, consumer, kafka_error, pending, store):
    next_publish = 0
    while True:
        if producer is not None and time.monotonic() >= next_publish:
            for ballot_id, ciphertext in pending():
                producer.produce(topic, key=ballot_id.encode("ascii"), value=ciphertext)
            next_publish = time.monotonic() + 5

        if producer is not None:
            producer.poll(0)
        if consumer is None:
            time.sleep(0.25)
            continue
        message = consumer.poll(0.25)
        if message is None:
            continue
        if message.error():
            if message.error().fatal():
                raise kafka_error(message.error())
            continue
        stored = store(message.key(), message.value())
        if stored:
            print("Ballot committed to storage.", flush=True)
        partitions = consumer.commit(message=message, asynchronous=False)
        for partition in partitions:
            if partition.error is not None:
                raise kafka_error(partition.error)


def broker_connection(broker):
    connection = {"bootstrap.servers": broker}
    if broker.startswith("127.0.0.1:"):
        # The local Docker broker can advertise localhost on an IPv4-only port.
        connection["broker.address.family"] = "v4"
    protocol = os.environ.get("ELECTIONCLOUD_KAFKA_SECURITY_PROTOCOL", "PLAINTEXT").upper()
    if protocol not in {"PLAINTEXT", "SSL", "SASL_SSL"}:
        raise ValueError("Kafka security protocol must be PLAINTEXT, SSL, or SASL_SSL.")
    connection["security.protocol"] = protocol
    if protocol == "SASL_SSL":
        username = os.environ.get("ELECTIONCLOUD_KAFKA_USERNAME")
        password = os.environ.get("ELECTIONCLOUD_KAFKA_PASSWORD")
        if not username or not password:
            raise ValueError("SASL_SSL requires Kafka username and password environment variables.")
        connection.update({
            "sasl.mechanism": os.environ.get("ELECTIONCLOUD_KAFKA_SASL_MECHANISM", "SCRAM-SHA-512"),
            "sasl.username": username,
            "sasl.password": password,
        })
    ca_path = os.environ.get("ELECTIONCLOUD_KAFKA_CA_PATH")
    if ca_path and protocol != "PLAINTEXT":
        connection["ssl.ca.location"] = ca_path
    return connection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("election.db"))
    parser.add_argument("--broker", default=os.environ.get("ELECTIONCLOUD_BROKER", "127.0.0.1:9092"))
    parser.add_argument("--role", choices=("both", "publisher", "consumer"), default="both")
    args = parser.parse_args()
    try:
        from confluent_kafka import Consumer, KafkaError, KafkaException, Producer
        from confluent_kafka.admin import AdminClient, NewTopic
    except ImportError:
        parser.exit(1, "Install the Kafka client with: python -m pip install -r requirements-kafka.txt\n")

    try:
        storage = configured_storage()
        if storage:
            topic = storage.topic()
            pending, store = storage.pending_ballots, storage.store_ballot
        else:
            topic = transaction(args.db, election_topic)
            pending = partial(transaction, args.db, pending_ballots)
            store = partial(transaction, args.db, store_ballot)
        connection = broker_connection(args.broker)
        producer = None
        consumer = None
        if args.role != "consumer":
            admin = AdminClient(connection)
            creation = admin.create_topics([NewTopic(topic, 1, 1)], request_timeout=10)
            try:
                creation[topic].result()
            except KafkaException as error:
                if error.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                    raise
            producer = Producer({
                **connection,
                "enable.idempotence": True,
                "delivery.timeout.ms": 10000,
            })
            print(f"Kafka publisher ready for {topic}.", flush=True)
        if args.role != "publisher":
            consumer = Consumer({
                **connection,
                "group.id": topic + "-sqlite",
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
                "allow.auto.create.topics": False,
            })
        try:
            if consumer is not None:
                consumer.subscribe([topic])
                print(f"Kafka worker listening on {topic}.", flush=True)
            relay(topic, producer, consumer, KafkaException, pending, store)
        finally:
            if consumer is not None:
                consumer.close()
    except KeyboardInterrupt:
        pass
    except (sqlite3.Error, KafkaException, StorageUnavailable, ValueError) as error:
        parser.exit(1, f"Kafka worker: {error}\n")


if __name__ == "__main__":
    main()
