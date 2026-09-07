"""审计管线：SQLite 事务串行冻结档案与盲下注，哈希链记录每次状态迁移。

B/H 使用全项目一次性消费凭证；失败也保留读取事实。文件产物采用原子替换，防止半写。
本地哈希链检测修改，不能替代外部时间戳服务或抵御同权限整库重写。
"""

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def now() -> str:
    """返回 UTC ISO 时间；无参数，使用系统时钟，仅提供本地顺序记录。"""
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> str:
    """生成确定性 JSON；参数必须可序列化，返回文本并拒绝非有限浮点。"""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    """计算规范化内容哈希；参数为 JSON 对象，返回 SHA256 十六进制摘要。"""
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    """原子落盘 JSON；输入路径和内容，无返回，临时文件与目标位于同一卷。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class AuditStore:
    """管理研究事务与访问凭证；参数为产物根目录，要求同一项目共用一个数据库。"""

    def __init__(self, root: Path):
        """初始化数据库；输入产物目录，无返回，数据库为审计事实源。"""
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "audit.sqlite3"
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, previous TEXT NOT NULL, hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS access (
                    segment TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                    batch_hash TEXT NOT NULL, timestamp TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS structures (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                    content TEXT NOT NULL, hash TEXT NOT NULL, timestamp TEXT NOT NULL);
            """)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """开启事务连接；无参数，产出连接，异常自动回滚并始终关闭。"""
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _append(self, db: sqlite3.Connection, kind: str, payload: Any) -> str:
        """在已有写事务中追加事件；输入连接/事件，返回链尾哈希。"""
        row = db.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        previous = row[0] if row else "0" * 64
        timestamp = now()
        hashed = digest({"timestamp": timestamp, "kind": kind, "payload": payload, "previous": previous})
        db.execute("INSERT INTO events(timestamp,kind,payload,previous,hash) VALUES(?,?,?,?,?)",
                   (timestamp, kind, canonical(payload), previous, hashed))
        return hashed

    def append(self, kind: str, payload: Any) -> str:
        """串行追加审计事件；输入事件类型和内容，返回哈希，事务防止并发分叉。"""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._append(db, kind, payload)

    def freeze(self, run_id: str, structure: dict[str, Any], bets: dict[str, Any]) -> str:
        """原子冻结结构和盲下注；返回内容哈希，重复 ID 或确认后登记会报错。"""
        content = {"structure": structure, "bets": bets}
        hashed = digest(content)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM access WHERE segment='B'").fetchone():
                raise ValueError("B 段已消费，禁止继续新增可正式确认的结构")
            db.execute("INSERT INTO structures VALUES(?,?,?,?,?)",
                       (structure["id"], run_id, canonical(content), hashed, now()))
            self._append(db, "structure_frozen", {"run_id": run_id, "id": structure["id"], "hash": hashed})
            write_json(self.root / run_id / structure["id"] / "frozen.json", content)
        return hashed

    def consume(self, segment: str, run_id: str, ids: list[str]) -> str:
        """冻结候选集合并消费 B/H 凭证；返回批次哈希，读失败也不可重新研究该段。"""
        if segment not in ("B", "H") or not ids:
            raise ValueError("必须指定 B/H 与非空冻结候选集")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id,hash FROM structures WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
            available = {row["id"]: row["hash"] for row in rows}
            if len(ids) != len(set(ids)) or not set(ids) <= available.keys():
                raise ValueError("批次包含重复或未冻结的档案")
            hashed = digest({key: available[key] for key in sorted(ids)})
            try:
                db.execute("INSERT INTO access VALUES(?,?,?,?)", (segment, run_id, hashed, now()))
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"{segment} 段已被读取，禁止重试或换批次") from exc
            self._append(db, "segment_consumed", {"segment": segment, "run_id": run_id, "batch_hash": hashed})
        return hashed

    def verify(self) -> dict[str, Any]:
        """验证事件链与冻结文件；无参数，返回校验摘要，任何篡改直接抛错。"""
        with self.connection() as db:
            rows = db.execute("SELECT * FROM events ORDER BY seq").fetchall()
            structures = db.execute("SELECT * FROM structures").fetchall()
            accesses = [dict(row) for row in db.execute("SELECT * FROM access").fetchall()]
        previous = "0" * 64
        for row in rows:
            content = {"timestamp": row["timestamp"], "kind": row["kind"],
                       "payload": json.loads(row["payload"]), "previous": previous}
            if row["previous"] != previous or row["hash"] != digest(content):
                raise ValueError(f"审计链被修改，事件 {row['seq']}")
            previous = row["hash"]
        for row in structures:
            if digest(json.loads(row["content"])) != row["hash"]:
                raise ValueError(f"数据库冻结档案被修改: {row['id']}")
            path = self.root / row["run_id"] / row["id"] / "frozen.json"
            if not path.exists() or digest(json.loads(path.read_text(encoding="utf-8"))) != row["hash"]:
                raise ValueError(f"冻结档案被修改或丢失: {row['id']}")
        return {"valid": True, "events": len(rows), "structures": len(structures),
                "anchor": previous, "access": accesses}

    def events(self) -> list[dict[str, Any]]:
        """返回按时间排序的审计记录；无参数，内容不包含密钥。"""
        with self.connection() as db:
            return [{**dict(row), "payload": json.loads(row["payload"])}
                    for row in db.execute("SELECT * FROM events ORDER BY seq").fetchall()]
