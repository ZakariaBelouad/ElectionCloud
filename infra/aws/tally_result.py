"""Count a closed Cosmos election using ElectionCloud and emit the proposed aggregate."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def aggregate(election_id, counts):
    return {
        "electionId": election_id,
        "schemaVersion": 1,
        "candidateTotals": counts,
        "totalCounted": sum(counts.values()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-key", required=True, type=Path)
    args = parser.parse_args()
    election_id = os.environ.get("ELECTIONCLOUD_ELECTION_ID")
    if not election_id or os.environ.get("ELECTIONCLOUD_STORAGE") != "cosmos":
        parser.error("Set ELECTIONCLOUD_STORAGE=cosmos and ELECTIONCLOUD_ELECTION_ID.")
    if os.environ.get("COSMOS_AUTH") != "azure-cli":
        parser.error("Set COSMOS_AUTH=azure-cli and sign in as the tally operator.")

    process = subprocess.run(
        [sys.executable, str(ROOT / "electioncloud.py"), "tally",
         "--private-key", str(args.private_key)],
        stdout=subprocess.PIPE, text=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"},
    )
    if process.returncode:
        return process.returncode
    print(json.dumps(aggregate(election_id, json.loads(process.stdout)), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
