"""Authenticated technical health and fallback notification entry points."""
from datetime import datetime
import json
import os
import re
from urllib.error import URLError
from urllib.request import urlopen

COLLECTION = "electioncloud_fallback_notifications"
EVENT_ID_PATTERN = r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}"


def supplemental_health(request):
    if request.method != "GET":
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
    if not isinstance(event, dict) or set(event) != {
        "event_id", "service", "severity", "status", "observed_at"
    }:
        return False
    if not all(isinstance(value, str) for value in event.values()):
        return False
    if not re.fullmatch(EVENT_ID_PATTERN, event["event_id"]):
        return False
    if event["service"] not in {"web", "worker", "kafka", "cosmos", "tally"}:
        return False
    if event["severity"] not in {"warning", "critical"}:
        return False
    if event["status"] not in {"firing", "resolved"}:
        return False
    try:
        return datetime.fromisoformat(event["observed_at"]).utcoffset() is not None
    except ValueError:
        return False


def enqueue(event):
    from google.api_core.exceptions import AlreadyExists
    from google.cloud import firestore

    document = firestore.Client().collection(COLLECTION).document(event["event_id"])
    try:
        document.create({**event, "delivery_state": "pending",
                         "queued_at": firestore.SERVER_TIMESTAMP})
    except AlreadyExists:
        existing = document.get().to_dict() or {}
        if any(existing.get(key) != value for key, value in event.items()):
            return "conflict"
        return "duplicate"
    return "queued"


def fallback_notification(request):
    if request.method != "POST":
        return {"error": "POST required"}, 405
    event = request.get_json(silent=True)
    if not validate(event):
        return {"error": "invalid technical event"}, 400

    try:
        status = enqueue(event)
    except Exception:
        # Storage failures may occur after a successful write. Retry the same ID.
        status = "retry"
    print(json.dumps({"signal": "fallback_notification", "status": status,
                      "event_id": event["event_id"], "service": event["service"]}),
          flush=True)
    return {"status": status}, {"queued": 202, "duplicate": 200,
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
                 "Authorization": "Bearer " + os.environ["NOTIFICATION_WEBHOOK_TOKEN"],
                 "Idempotency-Key": event["event_id"]},
    )
    with build_opener(RejectRedirects()).open(request, timeout=5) as response:
        if not 200 <= response.status < 300:
            raise OSError("Delivery not acknowledged")


def deliver(event_id):
    from google.cloud import firestore

    document = firestore.Client().collection(COLLECTION).document(event_id)
    snapshot = document.get()
    if not snapshot.exists:
        return "missing"
    record = snapshot.to_dict()
    if record["delivery_state"] == "delivered":
        return "duplicate"

    event = {key: record[key] for key in
             ("event_id", "service", "severity", "status", "observed_at")}
    send_notification(event)
    document.update({"delivery_state": "delivered",
                     "delivered_at": firestore.SERVER_TIMESTAMP})
    return "delivered"


def deliver_notification(request):
    if request.method != "POST":
        return {"error": "POST required"}, 405
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {"event_id"}:
        return {"error": "event_id required"}, 400
    event_id = body["event_id"]
    if not isinstance(event_id, str) or not re.fullmatch(EVENT_ID_PATTERN, event_id):
        return {"error": "invalid event_id"}, 400

    try:
        status = deliver(event_id)
    except Exception as error:
        status = "retry"
        print(json.dumps({"signal": "fallback_delivery_error", "event_id": event_id,
                          "error_type": type(error).__name__}), flush=True)
    print(json.dumps({"signal": "fallback_delivery", "status": status,
                      "event_id": event_id}), flush=True)
    return {"status": status}, {"delivered": 200, "duplicate": 200,
                                 "missing": 404, "retry": 503}[status]
