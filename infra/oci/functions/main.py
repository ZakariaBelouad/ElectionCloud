"""Authenticated technical health and fallback notification entry points."""
from datetime import datetime
import base64
import hmac
import json
import os
import re
from urllib.error import URLError
from urllib.request import urlopen

EVENT_ID_PATTERN = r"[A-Za-z0-9._:-]{8,128}"
REQUIRED = {"event_id", "service", "severity", "status", "observed_at"}


def supplemental_health(method):
    if method != "GET":
        return {"error": "GET required"}, 405

    url = os.environ.get("PRIMARY_HEALTH_URL", "")
    if not url.startswith("https://"):
        return {"status": "unconfigured"}, 503
    try:
        with urlopen(url, timeout=4) as response:
            healthy = 200 <= response.status < 300
    except (OSError, URLError):
        healthy = False
    status = "healthy" if healthy else "unhealthy"
    print(json.dumps({"signal": "primary_health", "status": status}), flush=True)
    return {"status": status}, 200 if healthy else 503


def validate(event):
    if not isinstance(event, dict) or set(event) not in (REQUIRED, REQUIRED | {"summary"}):
        return False
    if not all(isinstance(value, str) for value in (event[key] for key in REQUIRED)):
        return False
    if not re.fullmatch(EVENT_ID_PATTERN, event["event_id"]):
        return False
    if event["service"] not in {"web", "worker", "kafka", "cosmos", "tally", "alerts", "oci-standby"}:
        return False
    if event["severity"] not in {"info", "warning", "critical"}:
        return False
    if event["status"] not in {"firing", "resolved"}:
        return False
    try:
        offset = datetime.fromisoformat(event["observed_at"]).utcoffset()
        return offset is not None and offset.total_seconds() == 0
    except ValueError:
        return False


def resource_signer():
    from oci.auth.signers import get_resource_principals_signer

    return get_resource_principals_signer()


def read_secret(variable):
    from oci.secrets import SecretsClient

    client = SecretsClient({}, signer=resource_signer(), timeout=(2, 3))
    bundle = client.get_secret_bundle(os.environ[variable], stage="CURRENT")
    return base64.b64decode(bundle.data.secret_bundle_content.content).decode("utf-8")


class EventStore:
    def __init__(self, client, namespace, bucket):
        self.client = client
        self.location = (namespace, bucket)

    def process(self, event):
        from oci.exceptions import ServiceError

        key = (*self.location, "event-" + event["event_id"] + ".json")
        record = {**event, "delivery_state": "pending"}
        try:
            result = self.client.put_object(
                *key, json.dumps(record).encode(), if_none_match="*",
            )
            etag = result.headers["etag"]
        except ServiceError as error:
            if error.status != 412:
                raise
            result = self.client.get_object(*key)
            record = result.data.json()
            etag = result.headers["etag"]
            if any(record.get(field) != value for field, value in event.items()):
                return "conflict"
            if record["delivery_state"] == "delivered":
                return "duplicate"

        send_notification(event)
        record["delivery_state"] = "delivered"
        self.client.put_object(*key, json.dumps(record).encode(), if_match=etag)
        return "delivered"


def event_store():
    from oci.object_storage import ObjectStorageClient

    client = ObjectStorageClient({}, signer=resource_signer(), timeout=(2, 3))
    return EventStore(client, os.environ["EVENT_NAMESPACE"], os.environ["EVENT_BUCKET"])



def fallback_notification(method, event):
    if method != "POST":
        return {"error": "POST required"}, 405
    if not validate(event):
        return {"error": "invalid technical event"}, 400

    # The AWS router can include a free-form summary. Drop it before storage or delivery.
    event = {key: event[key] for key in REQUIRED}
    try:
        status = event_store().process(event)
    except Exception as error:
        print(json.dumps({"signal": "fallback_error", "event_id": event["event_id"],
                          "error_type": type(error).__name__}), flush=True)
        # Storage failures may occur after a successful write. Retry the same ID.
        status = "retry"
    print(json.dumps({"signal": "fallback_notification", "status": status,
                      "event_id": event["event_id"], "service": event["service"]}),
          flush=True)
    return {"status": status}, {"delivered": 200, "duplicate": 200,
                                 "conflict": 409, "retry": 503}[status]


def send_notification(event):
    """Send through the approved webhook, which must deduplicate the event ID."""
    from urllib.parse import urlsplit
    from urllib.request import HTTPRedirectHandler, Request, build_opener

    class RejectRedirects(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    url = os.environ["NOTIFICATION_WEBHOOK_URL"]
    endpoint = urlsplit(url)
    if endpoint.scheme != "https" or not endpoint.hostname or endpoint.username is not None:
        raise ValueError("An approved HTTPS webhook is required")
    request = Request(
        url, data=json.dumps(event).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + read_secret("WEBHOOK_SECRET_OCID"),
                 "Idempotency-Key": event["event_id"]},
    )
    with build_opener(RejectRedirects()).open(request, timeout=5) as response:
        if not 200 <= response.status < 300:
            raise OSError("Delivery not acknowledged")


def dispatch(method, headers, body):
    mode = os.environ.get("RECOVERY_MODE")
    if mode not in {"health", "fallback"}:
        return {"status": "unconfigured"}, 503
    auth = next((value for name, value in headers.items() if name.lower() == "authorization"), "")
    if isinstance(auth, list) and len(auth) == 1:
        auth = auth[0]
    if not isinstance(auth, str) or not auth.startswith("Bearer "):
        return {"error": "bearer credential required"}, 401
    try:
        secret = read_secret("CALLER_SECRET_OCID")
        if not secret:
            return {"status": "unconfigured"}, 503
    except Exception as error:
        print(json.dumps({"signal": "caller_secret_error", "error_type": type(error).__name__}), flush=True)
        return {"status": "retry"}, 503
    if not hmac.compare_digest(auth[7:].encode(), secret.encode()):
        return {"error": "invalid bearer credential"}, 403

    if mode == "health":
        return supplemental_health(method)
    if len(body) > 4096:
        return {"error": "event too large"}, 400
    try:
        event = json.loads(body)
    except (ValueError, UnicodeError):
        event = None
    return fallback_notification(method, event)


def handler(ctx, data=None):
    from fdk.response import Response

    payload, status = dispatch(ctx.Method(), ctx.HttpHeaders() or {}, data.read(4097) if data else b"")
    return Response(ctx, response_data=json.dumps(payload), status_code=status,
                    headers={"Content-Type": "application/json"})
