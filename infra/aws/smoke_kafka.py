"""Test the EC2 broker configuration locally against a disposable Docker project."""
import datetime
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time

from confluent_kafka import Consumer, KafkaError, KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

ASSETS = Path(__file__).resolve().parent
DNS = "localhost"
TOPIC = "electioncloud-" + "a" * 32
OTHER_TOPIC = "electioncloud-" + "b" * 32
KEY = b"a" * 32
VALUE = b"synthetic ciphertext fixture"


def credentials(directory):
    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, DNS)])
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - datetime.timedelta(minutes=5))
                   .not_valid_after(now + datetime.timedelta(days=1))
                   .add_extension(x509.SubjectAlternativeName([x509.DNSName(DNS)]), False)
                   .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
                   .sign(key, hashes.SHA256()))
    passwords = {name: secrets.token_hex(24) for name in ("admin", "worker", "publisher", "consumer", "tls")}
    for name, password in passwords.items():
        (directory / f"{name}-password").write_text(password, encoding="ascii")
    ca = directory / "ca.pem"
    ca.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    (directory / "broker.p12").write_bytes(pkcs12.serialize_key_and_certificates(
        b"kafka", key, certificate, None,
        serialization.BestAvailableEncryption(passwords["tls"].encode("ascii")),
    ))
    return {
        "bootstrap.servers": "localhost:9094",
        "broker.address.family": "v4",
        "security.protocol": "SASL_SSL",
        "ssl.ca.location": str(ca),
        "sasl.mechanism": "SCRAM-SHA-512",
        "sasl.username": "election-worker",
        "sasl.password": passwords["worker"],
    }, passwords


def consume(config):
    consumer = Consumer({
        **config, "group.id": f"{TOPIC}-sqlite", "auto.offset.reset": "earliest",
        "enable.auto.commit": False, "allow.auto.create.topics": False,
    })
    consumer.subscribe([TOPIC])
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            message = consumer.poll(1)
            if message is None:
                continue
            if message.error():
                raise KafkaException(message.error())
            assert (message.key(), message.value()) == (KEY, VALUE)
            return
        raise TimeoutError("Kafka did not deliver the fixture.")
    finally:
        consumer.close()


def main():
    project = "eckafka-" + secrets.token_hex(5)
    with tempfile.TemporaryDirectory(prefix="eckafka-") as scratch:
        directory = Path(scratch)
        data, secret = directory / "data", directory / "secret"
        data.mkdir()
        secret.mkdir()
        if sys.platform != "win32":
            data.chmod(0o777)  # Temporary parent remains private on the host.
            secret.chmod(0o755)
        config, passwords = credentials(secret)
        admin = {**config, "sasl.username": "broker-admin", "sasl.password": passwords["admin"], "log_level": 0}
        publisher = {**config, "sasl.username": "election-publisher",
                     "sasl.password": passwords["publisher"]}
        consumer = {**config, "sasl.username": "election-consumer",
                    "sasl.password": passwords["consumer"]}
        env = {
            **os.environ, "BROKER_DNS": DNS, "BROKER_BIND_IP": "127.0.0.1",
            "BROKER_DATA_DIR": data.as_posix(), "BROKER_SECRET_DIR": secret.as_posix(),
        }

        def compose(*args, check=True):
            subprocess.run(
                ["docker", "compose", "-p", project, "-f", str(ASSETS / "compose.yaml"), *args],
                env=env, check=check, timeout=150,
            )

        def ready():
            client = AdminClient(admin)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    client.list_topics(timeout=3)
                    return
                except KafkaException:
                    time.sleep(1)
            raise TimeoutError("Broker did not accept TLS/SCRAM admin connections.")

        try:
            compose("up", "-d")
            ready()
            compose("exec", "-T", "broker", "bash", "/assets/grant-worker.sh", TOPIC, "split")
            writer = AdminClient(publisher)
            writer.create_topics([NewTopic(TOPIC, 1, 1)], request_timeout=10)[TOPIC].result(15)
            denial = writer.create_topics([NewTopic(OTHER_TOPIC, 1, 1)], request_timeout=10)
            try:
                denial[OTHER_TOPIC].result(15)
            except KafkaException as error:
                assert error.args[0].code() == KafkaError.TOPIC_AUTHORIZATION_FAILED, error
            else:
                raise AssertionError("Publisher created a topic outside its ACL.")
            reader = AdminClient(consumer)
            denied_create = reader.create_topics([NewTopic(TOPIC, 1, 1)], request_timeout=10)
            try:
                denied_create[TOPIC].result(15)
            except KafkaException as error:
                assert error.args[0].code() == KafkaError.TOPIC_AUTHORIZATION_FAILED, error
            else:
                raise AssertionError("Consumer used the publisher's Create grant.")
            producer = Producer({**publisher, "enable.idempotence": True, "delivery.timeout.ms": 10000})
            deliveries = []
            producer.produce(TOPIC, key=KEY, value=VALUE,
                             on_delivery=lambda error, message: deliveries.append(error))
            assert producer.flush(15) == 0 and deliveries == [None], deliveries
            consume(consumer)
            print("PASS TLS/SCRAM, scoped create denial, idempotent produce and consume.", flush=True)
            metadata = (data / "meta.properties").read_bytes()
            compose("down")
            compose("up", "-d")
            ready()
            assert (data / "meta.properties").read_bytes() == metadata
            consume(consumer)
            print("PASS container replacement preserved KRaft metadata, ACLs and record.", flush=True)
        except Exception:
            compose("logs", "--tail", "40", "broker", check=False)
            raise
        finally:
            compose("down", check=False)


if __name__ == "__main__":
    main()
