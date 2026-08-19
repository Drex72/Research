from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TRANSLATION_PROMPT_VERSION = "1"
MIXING_PROMPT_VERSION = "1"
REVIEW_PROMPT_VERSION = "2"
BACK_TRANSLATION_PROMPT_VERSION = "1"


def stable_key(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def created_at() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArtifactCache:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.translations_path = self.directory / "translations.json"
        self.mixes_path = self.directory / "accepted_mixes.json"
        self.failures_path = self.directory / "failed_mixes.jsonl"
        self._lock = threading.RLock()

    def get_translation(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._read_map(self.translations_path).get(key)

    def save_translation(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            records = self._read_map(self.translations_path)
            records[key] = value
            self._write_map(self.translations_path, records)

    def get_mix(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._read_map(self.mixes_path).get(key)

    def save_mix(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            records = self._read_map(self.mixes_path)
            records[key] = value
            self._write_map(self.mixes_path, records)

    def save_failed_mix(self, value: dict[str, Any]) -> None:
        with self._lock:
            with self.failures_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(value, ensure_ascii=False) + "\n")

    @staticmethod
    def _read_map(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_map(path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)
