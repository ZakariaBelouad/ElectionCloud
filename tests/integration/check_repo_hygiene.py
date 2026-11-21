"""Fail if the repository tracks files that must stay local: databases, keys, env files, logs, caches,
or text that looks like a credential. Run from anywhere:  python tests/integration/check_repo_hygiene.py
"""

import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_NAMES = ("*.db", "*.db-*", "*.sqlite*", "*.pem", "*.key", "*.pfx", "*.p12", "*.log", "*.pyc",
                   ".env", ".env.*", "*.tfstate", "*.tfstate.*", "credentials*.json")
ALLOWED_NAMES = (".env.example",)
FORBIDDEN_DIRS = ("__pycache__", ".venv", "node_modules")
SECRET_PATTERNS = {
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "AWS access key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Azure storage/Cosmos account key": re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}"),
    "long base64 value assigned to a key/secret/password": re.compile(
        r"(?i)(key|secret|password|token)\s*[=:]\s*['\"]?[A-Za-z0-9+/]{40,}={0,2}['\"]?\s*$", re.M),
}


def tracked_files():
    output = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [name for name in output.decode().split("\0") if name]


def main():
    problems = []
    for name in tracked_files():
        path = Path(name)
        if path.name not in ALLOWED_NAMES and any(fnmatch(path.name, pattern) for pattern in FORBIDDEN_NAMES):
            problems.append(f"{name}: file type must not be tracked")
        if any(part in FORBIDDEN_DIRS for part in path.parts):
            problems.append(f"{name}: directory must not be tracked")
        file = ROOT / name
        if not file.is_file() or file.stat().st_size > 1_000_000:
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(f"{name}: binary file tracked; confirm it is intentional")
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                problems.append(f"{name}: looks like it contains a {label}")
    if problems:
        print("Repository hygiene check FAILED:")
        print("\n".join(" - " + item for item in problems))
        return 1
    print(f"Repository hygiene check passed ({len(tracked_files())} tracked files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
