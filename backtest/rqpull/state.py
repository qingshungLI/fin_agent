from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from zoneinfo import ZoneInfo

from .config import MANIFEST_PATH, ensure_directories


class Manifest:
    def __init__(self, path: Path = MANIFEST_PATH):
        self.path = path
        ensure_directories()
        self.data = self._read()

    def _read(self) -> dict:
        if not self.path.exists():
            return {"schema_version": 1, "tasks": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as fh:
            json.dump(self.data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
            temp = Path(fh.name)
        os.replace(temp, self.path)

    def task(self, name: str) -> dict:
        return self.data.setdefault("tasks", {}).setdefault(
            name, {"status": "PENDING", "chunks_done": [], "dirty_partitions": []}
        )

    def set_status(self, name: str, status: str, message: str | None = None) -> None:
        task = self.task(name)
        task["status"] = status
        task["last_update"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
        if message:
            task["message"] = message
        else:
            task.pop("message", None)
        self.flush()

    def is_done(self, name: str, chunk_id: str) -> bool:
        return chunk_id in self.task(name)["chunks_done"]

    def mark_chunk_done(self, name: str, chunk_id: str) -> None:
        task = self.task(name)
        if chunk_id not in task["chunks_done"]:
            task["chunks_done"].append(chunk_id)
            task["chunks_done"].sort()
        task["status"] = "RUNNING"
        task["last_update"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
        self.flush()

    def mark_dirty(self, name: str, partition: str, message: str) -> None:
        task = self.task(name)
        item = {"partition": partition, "message": message}
        task.setdefault("dirty_partitions", []).append(item)
        task["status"] = "DIRTY"
        self.flush()
