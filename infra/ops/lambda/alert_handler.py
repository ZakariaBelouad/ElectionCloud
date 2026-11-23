"""ElectionCloud technical alert router (AWS Lambda).

Accepts technical health events only. An event carries an ID, a service name, a
severity, the observation time and a status. Anything else is rejected, so voter
references, vote choices, session tokens and keys cannot travel through alerts.

Flow: validate -> claim the event ID (deduplication) -> notify administrators ->
on failure try the fallback route -> if both fail, release the claim and raise so
the caller (Lambda async retry or the dead-letter queue) can try again.
"""

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

SERVICES = ("web", "worker", "kafka", "cosmos", "tally", "alerts", "oci-standby")
SEVERITIES = ("info", "warning", "critical")
STATUSES = ("firing", "resolved")
REQUIRED = ("event_id", "service", "severity", "observed_at", "status")
OPTIONAL = ("summary",)
EVENT_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
SUMMARY = re.compile(r"^[A-Za-z0-9 .,:;()/_\-]{0,200}$")
# Defence in depth: a summary is free text, so refuse anything that looks like a secret.
SECRET_LOOKING = re.compile(r"[A-Za-z0-9_\-]{32,}|-----BEGIN|password|token|secret|voter|ballot|candidate", re.I)
DEDUP_TTL_SECONDS = 24 * 3600


class InvalidEvent(ValueError):
    pass


class NotificationFailed(RuntimeError):
    pass


def validate(event):
    """Return a clean copy of the event or raise InvalidEvent."""
    if not isinstance(event, dict):
        raise InvalidEvent("Event must be a JSON object.")
    unknown = sorted(set(event) - set(REQUIRED) - set(OPTIONAL))
    if unknown:
        raise InvalidEvent("Unexpected fields: " + ", ".join(unknown))
    missing = [name for name in REQUIRED if name not in event]
    if missing:
        raise InvalidEvent("Missing fields: " + ", ".join(missing))
    if not isinstance(event["event_id"], str) or not EVENT_ID.match(event["event_id"]):
        raise InvalidEvent("event_id must be 8-128 characters of letters, digits and . _ : -")
    if event["service"] not in SERVICES:
        raise InvalidEvent("service must be one of: " + ", ".join(SERVICES))
    if event["severity"] not in SEVERITIES:
        raise InvalidEvent("severity must be one of: " + ", ".join(SEVERITIES))
    if event["status"] not in STATUSES:
        raise InvalidEvent("status must be one of: " + ", ".join(STATUSES))
    observed = event["observed_at"]
    if not isinstance(observed, str):
        raise InvalidEvent("observed_at must be an ISO 8601 UTC string.")
    try:
        parsed = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError as error:
        raise InvalidEvent("observed_at must be an ISO 8601 UTC string.") from error
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise InvalidEvent("observed_at must be in UTC (end with Z).")
    summary = event.get("summary", "")
    if not isinstance(summary, str) or not SUMMARY.match(summary) or SECRET_LOOKING.search(summary):
        raise InvalidEvent("summary must be short technical text with no identifiers or secrets.")
    clean = {name: event[name] for name in REQUIRED}
    if summary:
        clean["summary"] = summary
    return clean


def from_alarm(detail):
    """Turn a CloudWatch alarm state-change detail into an ElectionCloud event."""
    name = str(detail.get("alarmName", ""))
    state = detail.get("state") or {}
    value = state.get("value", "")
    stamp = state.get("timestamp", "")
    match = re.match(r"^electioncloud-([a-z-]+?)-", name)
    service = match.group(1) if match and match.group(1) in SERVICES else "alerts"
    firing = value == "ALARM"
    observed = stamp.replace("+0000", "Z") if stamp else ""
    try:
        parsed = datetime.fromisoformat(observed.replace("Z", "+00:00"))
        observed = parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        observed = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = hashlib.sha256(f"{name}|{value}|{stamp}".encode()).hexdigest()[:24]
    event = {
        "event_id": f"cw-{digest}",
        "service": service,
        "severity": "critical" if firing else "info",
        "observed_at": observed,
        "status": "firing" if firing else "resolved",
    }
    if re.match(r"^[A-Za-z0-9 .,:;()/_\-]{1,200}$", name) and not SECRET_LOOKING.search(name):
        event["summary"] = f"CloudWatch alarm {name} is {value}"
    return event


def render(event):
    line = f"[{event['severity'].upper()}] {event['service']} {event['status']} at {event['observed_at']}"
    if event.get("summary"):
        line += f" - {event['summary']}"
    return {"subject": f"ElectionCloud {event['service']} {event['status']}", "body": line + f"\nevent: {event['event_id']}"}


# --- deduplication stores -------------------------------------------------------------

class MemoryDedup:
    """Local stand-in for the DynamoDB table. Same interface, no AWS needed."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.claims = {}

    def claim(self, event_id):
        now = self.clock()
        if self.claims.get(event_id, 0) > now:
            return False
        self.claims[event_id] = now + DEDUP_TTL_SECONDS
        return True

    def release(self, event_id):
        self.claims.pop(event_id, None)


class DynamoDedup:
    def __init__(self, table, client=None):
        if client is None:
            import boto3  # present in the Lambda runtime

            client = boto3.client("dynamodb")
        self.table, self.client = table, client

    def claim(self, event_id):
        now = int(time.time())
        try:
            self.client.put_item(
                TableName=self.table,
                Item={"event_id": {"S": event_id}, "expires_at": {"N": str(now + DEDUP_TTL_SECONDS)}},
                ConditionExpression="attribute_not_exists(event_id) OR expires_at < :now",
                ExpressionAttributeValues={":now": {"N": str(now)}},
            )
            return True
        except self.client.exceptions.ConditionalCheckFailedException:
            return False

    def release(self, event_id):
        self.client.delete_item(TableName=self.table, Key={"event_id": {"S": event_id}})


# --- senders --------------------------------------------------------------------------

class MockSender:
    """Records messages instead of sending them. Set fail=True to simulate an outage."""

    def __init__(self, name="mock", fail=False):
        self.name, self.fail, self.sent = name, fail, []

    def send(self, event, message):
        if self.fail:
            raise NotificationFailed(f"{self.name} destination unavailable")
        self.sent.append({"event": event, "message": message})


class SnsSender:
    """Primary route: SNS topic that fans out to the administrator subscriptions."""

    def __init__(self, topic_arn, client=None):
        if client is None:
            import boto3

            client = boto3.client("sns")
        self.topic_arn, self.client = topic_arn, client

    def send(self, event, message):
        try:
            self.client.publish(TopicArn=self.topic_arn, Subject=message["subject"][:100], Message=message["body"])
        except Exception as error:  # boto raises many types; all mean "not delivered"
            raise NotificationFailed(f"SNS publish failed: {type(error).__name__}") from error


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class HttpFallbackSender:
    """Fallback route: authenticated HTTPS POST of the event to the OCI Function (Person 3).

    Contract from infra/oci/README.md:
    - 200 means delivered, also when the same event was already delivered.
    - 400 (invalid event) and 409 (same ID, different content) are permanent refusals.
    - 401 and 403 mean the bearer credential is missing or wrong.
    - 503 and timeouts are temporary. The Lambda retries with the same event.
    The gateway route requires a bearer credential from token_provider.
    """

    PERMANENT = {400: "invalid event", 409: "event ID reused with different content",
                 401: "missing or invalid bearer credential", 403: "caller not allowed to invoke the function"}

    def __init__(self, url, token_provider=None, timeout=18, opener=None):
        if not url.startswith("https://"):
            raise ValueError("Fallback URL must use https.")
        self.url, self.token_provider, self.timeout = url, token_provider, timeout
        self.opener = opener or urllib.request.build_opener(RejectRedirects()).open

    def send(self, event, message):
        headers = {"Content-Type": "application/json"}
        if self.token_provider is not None:
            try:
                headers["Authorization"] = "Bearer " + self.token_provider()
            except Exception as error:
                raise NotificationFailed(f"fallback token unavailable: {type(error).__name__}") from error
        request = urllib.request.Request(self.url, data=json.dumps(event).encode(), headers=headers, method="POST")
        try:
            with self.opener(request, timeout=self.timeout) as response:  # noqa: S310 (https enforced)
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        except Exception as error:
            raise NotificationFailed(f"fallback call failed: {type(error).__name__}") from error
        if status == 200:
            return
        if status in self.PERMANENT:
            raise NotificationFailed(f"fallback refused the event (HTTP {status}: {self.PERMANENT[status]})")
        raise NotificationFailed(f"fallback temporarily unavailable (HTTP {status})")


# --- routing --------------------------------------------------------------------------

def route(event, dedup, primary, fallback=None, log=print):
    """Validate, deduplicate and deliver one event. Returns a small status dict."""
    clean = validate(event)
    event_id = clean["event_id"]
    if not dedup.claim(event_id):
        log(json.dumps({"msg": "duplicate", "event_id": event_id}))
        return {"result": "duplicate", "event_id": event_id}
    message = render(clean)
    try:
        primary.send(clean, message)
        log(json.dumps({"msg": "sent", "route": "primary", "event_id": event_id}))
        return {"result": "sent", "route": "primary", "event_id": event_id}
    except NotificationFailed as primary_error:
        log(json.dumps({"msg": "primary_failed", "event_id": event_id, "reason": str(primary_error)}))
    if fallback is not None:
        try:
            fallback.send(clean, message)
            log(json.dumps({"msg": "sent", "route": "fallback", "event_id": event_id}))
            return {"result": "sent", "route": "fallback", "event_id": event_id}
        except NotificationFailed as fallback_error:
            log(json.dumps({"msg": "fallback_failed", "event_id": event_id, "reason": str(fallback_error)}))
    dedup.release(event_id)  # nobody was told, so a retry must be allowed to try again
    log(json.dumps({"msg": "notification_failed", "event_id": event_id}))
    raise NotificationFailed(f"No route delivered event {event_id}")


def fallback_secret_provider(secret_arn):
    from boto3 import client
    from botocore.config import Config

    secrets = client("secretsmanager", config=Config(
        connect_timeout=2, read_timeout=3, retries={"total_max_attempts": 1},
    ))

    def token():
        value = secrets.get_secret_value(SecretId=secret_arn)["SecretString"]
        if not value or value != value.strip():
            raise ValueError("Fallback bearer credential must be a nonempty string.")
        return value

    return token


def build_from_environment():
    topic = os.environ["ADMIN_TOPIC_ARN"]
    fallback_url = os.environ.get("FALLBACK_URL", "")
    fallback = None
    if fallback_url:
        provider = fallback_secret_provider(os.environ["FALLBACK_SECRET_ARN"])
        fallback = HttpFallbackSender(fallback_url, token_provider=provider)
    return (
        DynamoDedup(os.environ["DEDUP_TABLE"]),
        SnsSender(topic),
        fallback,
    )


_RUNTIME = None


def handler(event, context=None):
    """Lambda entry point. Accepts a direct ElectionCloud event or an EventBridge alarm event."""
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = build_from_environment()
    dedup, primary, fallback = _RUNTIME
    if isinstance(event, dict) and event.get("detail-type") == "CloudWatch Alarm State Change":
        event = from_alarm(event.get("detail", {}))
    try:
        return route(event, dedup, primary, fallback)
    except InvalidEvent as error:
        print(json.dumps({"msg": "invalid_event", "reason": str(error)}))
        return {"result": "rejected", "reason": str(error)}
