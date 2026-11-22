#!/usr/bin/env bash
set -euo pipefail
topic=${1:-}
mode=${2:-}
if [[ ! "$topic" =~ ^electioncloud-[a-f0-9]{32}$ || ! "$mode" =~ ^(combined|split)$ ]]; then
    printf '%s\n' 'Pass the verified election topic and combined or split.' >&2
    exit 2
fi
args=(--bootstrap-server "${BROKER_DNS}:9094" --command-config /tmp/electioncloud-admin.properties)
acl=/opt/kafka/bin/kafka-acls.sh

if [[ "$mode" == combined ]]; then
    "$acl" "${args[@]}" --add --allow-principal User:election-worker \
        --topic "$topic" --operation Create --operation Describe --operation Write --operation Read
    "$acl" "${args[@]}" --add --allow-principal User:election-worker \
        --group "${topic}-sqlite" --operation Read
else
    "$acl" "${args[@]}" --add --allow-principal User:election-publisher \
        --topic "$topic" --operation Create --operation Describe --operation Write
    "$acl" "${args[@]}" --add --allow-principal User:election-consumer \
        --topic "$topic" --operation Describe --operation Read
    "$acl" "${args[@]}" --add --allow-principal User:election-consumer \
        --group "${topic}-sqlite" --operation Read
fi
"$acl" "${args[@]}" --list --topic "$topic" --group "${topic}-sqlite"
