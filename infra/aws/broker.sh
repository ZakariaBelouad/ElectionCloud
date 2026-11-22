#!/usr/bin/env bash
set -euo pipefail
umask 077

secret() {
    local value
    value=$(cat "/secrets/$1") || exit 1
    if [[ ! "$value" =~ ^[A-Za-z0-9]{24,}$ ]]; then
        printf 'Invalid secret file: %s\n' "$1" >&2
        exit 1
    fi
    printf '%s' "$value"
}

admin=$(secret admin-password)
tls=$(secret tls-password)
cat > /tmp/electioncloud-server.properties <<EOF
process.roles=broker,controller
node.id=1
controller.quorum.voters=1@127.0.0.1:9093
controller.listener.names=CONTROLLER
listeners=CLIENT://0.0.0.0:9094,CONTROLLER://127.0.0.1:9093
advertised.listeners=CLIENT://${BROKER_DNS}:9094
listener.security.protocol.map=CLIENT:SASL_SSL,CONTROLLER:PLAINTEXT
inter.broker.listener.name=CLIENT
sasl.enabled.mechanisms=SCRAM-SHA-512
sasl.mechanism.inter.broker.protocol=SCRAM-SHA-512
listener.name.client.scram-sha-512.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="broker-admin" password="$admin";
ssl.keystore.type=PKCS12
ssl.keystore.location=/secrets/broker.p12
ssl.keystore.password=$tls
ssl.truststore.type=PEM
ssl.truststore.location=/secrets/ca.pem
authorizer.class.name=org.apache.kafka.metadata.authorizer.StandardAuthorizer
super.users=User:broker-admin;User:ANONYMOUS
allow.everyone.if.no.acl.found=false
auto.create.topics.enable=false
log.dirs=/data
default.replication.factor=1
offsets.topic.replication.factor=1
transaction.state.log.replication.factor=1
transaction.state.log.min.isr=1
EOF

if [[ ! -f /data/meta.properties ]]; then
    if [[ -n "$(find /data -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
        printf '%s\n' 'Kafka data directory is nonempty and has no meta.properties.' >&2
        exit 1
    fi
    worker=$(secret worker-password)
    publisher=$(secret publisher-password)
    consumer=$(secret consumer-password)
    /opt/kafka/bin/kafka-storage.sh format -c /tmp/electioncloud-server.properties \
        -t "$(/opt/kafka/bin/kafka-storage.sh random-uuid)" \
        --add-scram "SCRAM-SHA-512=[name=broker-admin,password=$admin]" \
        --add-scram "SCRAM-SHA-512=[name=election-worker,password=$worker]" \
        --add-scram "SCRAM-SHA-512=[name=election-publisher,password=$publisher]" \
        --add-scram "SCRAM-SHA-512=[name=election-consumer,password=$consumer]"
fi

cat > /tmp/electioncloud-admin.properties <<EOF
security.protocol=SASL_SSL
sasl.mechanism=SCRAM-SHA-512
sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="broker-admin" password="$admin";
ssl.truststore.type=PEM
ssl.truststore.location=/secrets/ca.pem
EOF

exec /opt/kafka/bin/kafka-server-start.sh /tmp/electioncloud-server.properties
