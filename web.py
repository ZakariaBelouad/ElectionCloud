"""Loopback-only browser interface for the ElectionCloud academic demo."""

import argparse
import os
import secrets
import sqlite3
import time
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from electioncloud import StorageUnavailable, configured_storage, execute


class ElectionPage(BaseHTTPRequestHandler):
    def action(self, command, **fields):
        args = argparse.Namespace(db=self.server.database, command=command, **fields)
        return self.server.storage.run(args) if self.server.storage else execute(args)

    def submit_ballot(self, session, candidate):
        fields = {"session": session, "candidate": candidate}
        if not self.server.kafka:
            return self.action("vote", **fields)
        deadline = time.monotonic() + 4
        receipt = self.action("queue_vote", **fields)
        while receipt["status"] == "pending" and time.monotonic() < deadline:
            time.sleep(0.2)
            receipt = self.action("receipt", session=session)
        return receipt

    def page(self, notice="", status=200):
        turnout = self.action("turnout")
        closed = turnout["closed"]
        nonce = f'<input type="hidden" name="nonce" value="{self.server.nonce}">'
        forms = "<p>This election is closed. The operator can tally it from the terminal.</p>"
        if not closed:
            options = "".join(
                f'<label class="option"><input type="radio" name="candidate" '
                f'value="{number}" required> {escape(name)}</label>'
                for number, name in self.action("candidates").items()
            )
            forms = f"""
            <div class="grid">
              <section><h2>Issue a voting session</h2>
                <p>Use a fictional voter reference after the eligibility check.</p>
                <form action="/issue" method="post">{nonce}
                  <label>Voter reference<input name="reference" maxlength="100" required></label>
                  <button>Issue session</button>
                </form>
              </section>
              <section><h2>Cast a ballot</h2>
                <form action="/vote" method="post">{nonce}
                  <label>Session token<input name="session" maxlength="100" autocomplete="off" required></label>
                  <fieldset><legend>Choose a candidate</legend>{options}</fieldset>
                  <button>Confirm ballot</button>
                </form>
              </section>
            </div>"""
        if self.server.kafka:
            forms += f"""
            <section><h2>Check ballot receipt</h2>
              <form action="/receipt" method="post">{nonce}
                <label>Session token<input name="session" maxlength="100" autocomplete="off" required></label>
                <button>Check receipt</button>
              </form>
            </section>"""
        message = f'<p class="notice" role="status">{escape(notice)}</p>' if notice else ""
        body = f"""<!doctype html>
        <html lang="en"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>ElectionCloud</title>
        <style>
          * {{box-sizing:border-box}}
          body {{font:1rem/1.5 system-ui,sans-serif;margin:0;background:#f1f5fa;color:#16283d}}
          header {{background:#112942;color:white;padding:2.5rem max(1.25rem,calc((100% - 58rem)/2))}}
          header p {{margin:0;color:#b8d1e9}}
          h1 {{font-size:clamp(2rem,6vw,3.5rem);margin:0}}
          main {{max-width:60.5rem;margin:auto;padding:1.25rem}}
          h2 {{margin:0 0 0.5rem;font-size:1.3rem}}
          .summary {{display:flex;align-items:center;justify-content:space-between;gap:1rem}}
          .summary p {{margin:0}}
          .grid {{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,20rem),1fr));gap:1rem}}
          section,.notice {{background:white;border:1px solid #cedae7;border-radius:1rem;padding:1.3rem;margin-bottom:1rem}}
          .notice {{border-left:5px solid #17655d;overflow-wrap:anywhere}}
          label {{display:block;font-weight:600}}
          input:not([type=radio]) {{display:block;width:100%;border:1px solid #71859b;border-radius:.5rem;padding:.65rem;margin:.25rem 0 1rem;font:inherit}}
          fieldset {{border:1px solid #a4b4c5;border-radius:.5rem;margin:0 0 1rem}}
          .option {{padding:.35rem}}
          button {{background:#175f57;color:white;border:0;border-radius:.5rem;padding:.7rem 1rem;font:inherit;font-weight:700;cursor:pointer}}
          :focus-visible {{outline:3px solid #135bb2;outline-offset:3px}}
        </style></head><body>
        <header><p>Polling station demo{" · Kafka ingestion" if self.server.kafka else ""}</p><h1>ElectionCloud</h1></header>
        <main><section class="summary" aria-label="Turnout">
          <p><strong>{turnout["accepted_ballots"]}</strong> accepted ballots</p>
          <p><strong>{"Closed" if closed else "Voting open"}</strong></p>
        </section>{message}{forms}</main></body></html>""".encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        if self.headers.get("Host", "").lower() in self.server.allowed_hosts:
            return True
        self.send_error(403)
        return False

    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.valid_host():
            if self.path == "/":
                try:
                    self.page()
                except (sqlite3.Error, StorageUnavailable):
                    self.send_error(503, "Election database temporarily unavailable.")
            else:
                self.send_error(404)

    def do_POST(self):
        if not self.valid_host():
            return
        if self.path not in {"/issue", "/vote"} and not (
            self.path == "/receipt" and self.server.kafka
        ):
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("Invalid form size.")
            fields = parse_qs(self.rfile.read(length).decode("utf-8"), max_num_fields=4)
            nonce = fields.get("nonce", [""])[0]
            if not secrets.compare_digest(nonce.encode(), self.server.nonce.encode()):
                self.send_error(403)
                return
            if self.path == "/issue":
                reference = fields.get("reference", [""])[0].strip()
                if not 0 < len(reference) <= 100:
                    raise ValueError("Enter a voter reference between 1 and 100 characters.")
                token = self.action("issue", voter_reference=reference)
                self.page(f"Session issued. Copy this token to cast one ballot: {token}")
            else:
                session = fields.get("session", [""])[0].strip()
                if not 0 < len(session) <= 100:
                    raise ValueError("Enter your session token.")
                if self.path == "/receipt":
                    receipt = self.action("receipt", session=session)
                else:
                    candidate = fields.get("candidate", [""])[0]
                    if not (0 < len(candidate) <= 18 and candidate.isascii() and candidate.isdecimal()):
                        raise ValueError("Choose a candidate.")
                    receipt = self.submit_ballot(session, int(candidate))
                if receipt["status"] == "pending":
                    self.page(
                        "Ballot queued. Use your session token to check for a receipt. "
                        "Your choice is locked.",
                        status=202,
                    )
                elif receipt["status"] == "unknown":
                    self.page("No ballot is associated with that session token.", status=404)
                else:
                    self.page(f"Ballot accepted. Receipt: {receipt['ballot_id']}")
        except ValueError as error:
            self.page(str(error), status=400)
        except (sqlite3.Error, StorageUnavailable):
            self.send_error(503, "Election database temporarily unavailable.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("election.db"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--bind", default="127.0.0.1", help="Local address to listen on.")
    parser.add_argument("--kafka", action="store_true", help="Queue ballots for the Kafka worker.")
    args = parser.parse_args()
    try:
        storage = configured_storage()
        turnout = argparse.Namespace(db=args.db, command="turnout")
        if storage:
            storage.run(turnout)
        else:
            execute(turnout)
        with HTTPServer((args.bind, args.port), ElectionPage) as server:
            server.database = args.db
            server.storage = storage
            server.kafka = args.kafka
            server.allowed_hosts = {f"127.0.0.1:{server.server_port}"}
            public_host = os.environ.get("ELECTIONCLOUD_PUBLIC_HOST", "").strip().lower()
            if public_host:
                server.allowed_hosts.add(public_host)
            server.nonce = secrets.token_urlsafe(32)
            print(f"ElectionCloud: http://127.0.0.1:{server.server_port}", flush=True)
            server.serve_forever()
    except (OSError, sqlite3.Error, StorageUnavailable, ValueError) as error:
        parser.exit(1, f"ElectionCloud: {error}\n")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
