"""Content-addressed panel cache with atomic publication and integrity checks."""
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

import pandas as pd

from engine.audit import digest, write_json
from engine.data import MarketPanel, build_panel


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cached_panel(data_root, config, cache_root, *, start=None, end=None):
    data_root, cache_root = Path(data_root), Path(cache_root)
    # Cache identity includes all input data content and implementation. Never
    # accept a same-sized/mmtime-only replacement of source data.
    inputs = {str(p.relative_to(data_root)): file_hash(p) for p in sorted(data_root.rglob("*.parquet"))}
    code = {p.name: file_hash(p) for p in [Path(__file__).parent / name for name in ("data.py", "config.py", "cache.py", "research_fields.py")]}
    identity = {"data": inputs, "code": code, "config": config.model_dump(include={
                    "start", "end", "max_symbols", "seed", "industry_policy", "industry_source", "auction_policy",
                    "commission_bp", "slippage_bp", "stamp_tax_bp", "data_profile"}),
                "start": start, "end": end}
    key = digest(identity)
    target = cache_root / key
    if config.cache and target.exists():
        meta = json.loads((target / "manifest.json").read_text(encoding='utf-8'))
        if meta["identity"] != identity:
            raise ValueError("Panel cache identity mismatch")
        for name, expected in meta["files"].items():
            if file_hash(target / name) != expected:
                raise ValueError("Corrupt panel cache: " + name)
        groups = {}
        for group in ("fields", "labels"):
            groups[group] = {name: pd.read_parquet(target / f"{group}-{name}.parquet")
                             for name in meta[group]}
        return MarketPanel(groups["fields"], groups["labels"], meta["report"], meta["sources"]), True
    panel = build_panel(data_root, config, start=start, end=end)
    if not config.cache:
        return panel, False
    cache_root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="building-", dir=cache_root))
    try:
        names = {}
        for group in ("fields", "labels"):
            values = getattr(panel, group)
            names[group] = list(values)
            for name, frame in values.items():
                frame.to_parquet(tmp / f"{group}-{name}.parquet")
        checksums = {p.name: file_hash(p) for p in tmp.glob("*.parquet")}
        write_json(tmp / "manifest.json", {"identity": identity, **names, "files": checksums,
                    "report": panel.report, "sources": panel.manifest})
        try:
            os.rename(tmp, target)
        except FileExistsError:
            shutil.rmtree(tmp)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return panel, False
