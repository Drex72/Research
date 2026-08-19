from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


GENESIS = "0" * 64


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def event_hash(event_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(event_without_hash)).hexdigest()


def read_verified(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    previous = GENESIS
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            event = json.loads(line)
            stored_hash = event.pop("event_sha256")
            if event.get("prev_event_sha256") != previous:
                raise ValueError(f"trace chain mismatch at line {line_number}")
            computed = event_hash(event)
            if computed != stored_hash:
                raise ValueError(f"trace hash mismatch at line {line_number}")
            event["event_sha256"] = stored_hash
            events.append(event)
            previous = stored_hash
    return events


class TraceWriter:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = read_verified(path)
        self.previous = existing[-1]["event_sha256"] if existing else GENESIS
        self.completed = {e["run_unit_id"] for e in existing if e.get("status") == "complete"}

    def append(self, value: dict[str, Any]) -> None:
        event = dict(value)
        event["prev_event_sha256"] = self.previous
        event["event_sha256"] = event_hash(event)
        encoded = canonical(event) + b"\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, encoded)
            os.fsync(fd)
        finally:
            os.close(fd)
        self.previous = event["event_sha256"]
        if event.get("status") == "complete":
            self.completed.add(event["run_unit_id"])

