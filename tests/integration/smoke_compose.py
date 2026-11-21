"""Repeatable synthetic-election smoke test against a throwaway Docker Compose project.

Runs on any machine with Docker + Compose + Python 3.10+. No cloud credentials, no real data.
Everything it creates lives in one uniquely named Compose project and is removed afterwards.

    python tests/integration/smoke_compose.py
    python tests/integration/smoke_compose.py --evidence smoke-evidence.json

Exit code 0 means every check matched its expected result.
"""

import argparse
import json
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = ("Candidate A", "Candidate B")


class Smoke:
    def __init__(self, project, port, timeout):
        self.project, self.port, self.timeout = project, port, timeout
        self.base = f"http://127.0.0.1:{port}"
        self.nonce = None
        self.results = []

    # --- plumbing -------------------------------------------------------------------
    def compose(self, *args, check=True, timeout=None):
        env_port = {"ELECTIONCLOUD_PORT": str(self.port)}
        import os

        process = subprocess.run(
            ["docker", "compose", "-p", self.project, *args],
            cwd=ROOT, capture_output=True, text=True, timeout=timeout or self.timeout,
            env={**os.environ, **env_port},
        )
        if check and process.returncode != 0:
            raise RuntimeError(f"docker compose {' '.join(args[:3])} failed:\n{process.stdout[-800:]}{process.stderr[-800:]}")
        return process

    def admin(self, *args, check=True):
        return self.compose("run", "--rm", "--no-deps", "admin", *args, check=check)

    def http(self, path, fields=None):
        data = urllib.parse.urlencode({"nonce": self.nonce, **fields}).encode() if fields is not None else None
        request = urllib.request.Request(self.base + path, data=data)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode()

    def notice(self, html):
        match = re.search(r'<p class="notice" role="status">(.*?)</p>', html, re.S)
        return re.sub(r"&#x27;|&quot;", "'", match.group(1)) if match else ""

    def check(self, name, expected, observed, ok):
        self.results.append({"check": name, "expected": expected, "observed": observed, "ok": bool(ok)})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}\n       expected: {expected}\n       observed: {observed}", flush=True)
        return ok

    # --- steps ----------------------------------------------------------------------
    def start(self, skip_build):
        if not skip_build:
            self.compose("build", "web", "worker", timeout=1500)
        self.admin("init", "--private-key", "/keys/tally.pem", *CANDIDATES)
        self.compose("up", "-d", "--wait", "--wait-timeout", "240")
        _, page = self.http("/")
        found = re.search(r'name="nonce" value="([^"]+)"', page)
        if not found:
            raise RuntimeError("Could not read the form nonce from the home page.")
        self.nonce = found.group(1)

    def issue(self, reference):
        status, html = self.http("/issue", {"reference": reference})
        token = re.search(r"cast one ballot: (\S+)", self.notice(html))
        return status, (token.group(1) if token else None), self.notice(html)

    def cast(self, token, candidate):
        status, html = self.http("/vote", {"session": token, "candidate": str(candidate)})
        return status, self.notice(html)

    def wait_for_receipt(self, token):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            status, html = self.http("/receipt", {"session": token})
            message = self.notice(html)
            if message.startswith("Ballot accepted. Receipt: "):
                return message.split("Receipt: ", 1)[1]
            time.sleep(2)
        return None

    def turnout(self):
        _, html = self.http("/")
        found = re.search(r"<strong>(\d+)</strong> accepted ballots", html)
        return (int(found.group(1)) if found else None), html

    def run(self):
        status, token1, _ = self.issue("SMOKE-001")
        self.check("staff issues a one-time session", "200 and a token", f"{status}, token={'yes' if token1 else 'no'}", status == 200 and token1)
        status, again, message = self.issue("SMOKE-001")
        self.check("second session for same voter is refused", "400 'already has a session or has voted'", f"{status} {message}",
                   status == 400 and "already has a session" in message)

        status, message = self.cast(token1, 1)
        receipt = message.split("Receipt: ", 1)[1] if message.startswith("Ballot accepted. Receipt: ") else None
        if status == 202:  # queued through Kafka: the browser must be able to collect the durable receipt later
            receipt = self.wait_for_receipt(token1)
        self.check("cast returns a durable receipt (pending first is fine)", "receipt id after the worker stores the ballot",
                   receipt or f"none ({status} {message})", receipt)

        status, message = self.cast(token1, 1)
        count, _ = self.turnout()
        self.check("replaying the same session adds no ballot", "turnout still 1", f"{status} {message[:40]}... turnout={count}", count == 1)

        _, token2, _ = self.issue("SMOKE-002")
        _, token3, _ = self.issue("SMOKE-003")
        for token, choice in ((token2, 1), (token3, 2)):
            self.cast(token, choice)
            self.wait_for_receipt(token)
        count, html = self.turnout()
        self.check("turnout counts accepted ballots during voting", "3", count, count == 3)
        text = re.sub(r"<[^>]+>", " ", html)
        leaked = re.search(r"Candidate [AB][^\n]{0,30}\d", text)
        self.check("no candidate totals while voting is open", "no per-candidate numbers on the page", "none" if not leaked else leaked.group(0), not leaked)

        early = self.admin("tally", "--private-key", "/keys/tally.pem", check=False)
        self.check("tally refused before close", "non-zero exit, 'Close the election'", f"exit {early.returncode}",
                   early.returncode != 0 and "Close the election" in early.stderr + early.stdout)

        closed = None
        for _ in range(15):
            closed = self.admin("close", check=False)
            if closed.returncode == 0:
                break
            time.sleep(2)
        self.check("election closes once the outbox is empty", "'Election closed.'", (closed.stdout or closed.stderr).strip()[-80:], closed.returncode == 0)

        status, _, message = self.issue("SMOKE-004")
        self.check("no new session after close", "400 'The election is closed.'", f"{status} {message}", status == 400 and "closed" in message)
        _, html = self.http("/")
        self.check("dashboard shows Closed", "Closed", "Closed" if "Closed</strong>" in html else "open", "Closed</strong>" in html)

        final = self.admin("tally", "--private-key", "/keys/tally.pem", check=False)
        counts = None
        try:
            counts = json.loads(final.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            pass
        self.check("tally after close matches the synthetic ballots", {"Candidate A": 2, "Candidate B": 1}, counts, counts == {"Candidate A": 2, "Candidate B": 1})

    def teardown(self):
        self.compose("down", "-v", "--remove-orphans", check=False, timeout=300)


def revision():
    process = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return (process.stdout.strip() or "unknown") + (" (+uncommitted changes)" if dirty else "")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default="ec-smoke-" + secrets.token_hex(4), help="Compose project name (must be new).")
    parser.add_argument("--port", type=int, default=0, help="Host port (default: a free one).")
    parser.add_argument("--timeout", type=int, default=600, help="Per-command timeout in seconds.")
    parser.add_argument("--skip-build", action="store_true", help="Reuse existing images.")
    parser.add_argument("--keep", action="store_true", help="Leave the project running for inspection.")
    parser.add_argument("--evidence", type=Path, help="Write a JSON record of expected vs observed results.")
    args = parser.parse_args()
    if not args.project.startswith("ec-smoke-"):
        parser.error("project name must start with ec-smoke- so cleanup can never touch another project")

    smoke = Smoke(args.project, args.port or free_port(), args.timeout)
    started = datetime.now(timezone.utc)
    error = None
    try:
        smoke.start(args.skip_build)
        smoke.run()
    except Exception as exc:  # report, then always clean up
        error = str(exc)
        print(f"ERROR: {error}", file=sys.stderr)
        logs = smoke.compose("logs", "--tail", "40", "web", "worker", check=False)
        print(logs.stdout[-2000:], file=sys.stderr)
    finally:
        if not args.keep:
            smoke.teardown()

    passed = error is None and bool(smoke.results) and all(item["ok"] for item in smoke.results)
    if args.evidence:
        args.evidence.write_text(json.dumps({
            "revision": revision(), "project": args.project, "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "scope": "local Docker Compose, synthetic data, SQLite + Docker Kafka", "error": error,
            "results": smoke.results, "passed": passed,
        }, indent=2))
    print(f"\n{'SMOKE TEST PASSED' if passed else 'SMOKE TEST FAILED'} ({sum(i['ok'] for i in smoke.results)}/{len(smoke.results)} checks) at {revision()}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
