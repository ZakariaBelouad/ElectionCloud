"""Run the web app and its Kafka publisher in the App Service container."""

import argparse
import signal
import subprocess
import sys
import time
from threading import Event


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="/data/election.db")
    parser.add_argument("--port", default="8767")
    args = parser.parse_args()

    stopped = Event()

    def stop(signum, frame):
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    web = subprocess.Popen([
        sys.executable, "web.py", "--db", args.db, "--bind", "0.0.0.0",
        "--port", args.port, "--kafka",
    ])
    publisher = None
    retry_at = 0
    try:
        while not stopped.wait(0.25):
            if web.poll() is not None:
                return 1
            if publisher is not None and publisher.poll() is not None:
                print("Kafka publisher exited. Retrying in 5 seconds.", flush=True)
                publisher = None
                retry_at = time.monotonic() + 5
            if publisher is None and time.monotonic() >= retry_at:
                publisher = subprocess.Popen([
                    sys.executable, "kafka_worker.py", "--db", args.db, "--role", "publisher",
                ])
        return 0
    finally:
        children = [process for process in (publisher, web) if process is not None]
        for process in children:
            if process.poll() is None:
                process.terminate()
        for process in children:
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
