from __future__ import annotations

from pathlib import Path

import duckdb

from .config import ARCHIVE_ROOT, STD_ROOT, WAREHOUSE_PATH, ensure_directories


def _view_name(path: Path) -> str:
    return "v_" + "_".join(path.relative_to(STD_ROOT).parts).replace("=", "_").replace("-", "_")


def build_views() -> list[str]:
    ensure_directories()
    WAREHOUSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[Path]] = {}
    for path in STD_ROOT.rglob("*.parquet"):
        if path.name.startswith("._"):
            continue
        relative = path.relative_to(STD_ROOT)
        top = relative.parts[0].replace(".parquet", "")
        groups.setdefault(top, []).append(path)
    legacy = sorted(p for p in (ARCHIVE_ROOT / "legacy_adjusted").rglob("*.parquet") if not p.name.startswith("._"))
    if legacy:
        groups["legacy_adjusted"] = legacy
    created = []
    con = duckdb.connect(str(WAREHOUSE_PATH))
    try:
        for name, files in sorted(groups.items()):
            file_sql = "[" + ",".join("'" + str(p).replace("'", "''") + "'" for p in sorted(files)) + "]"
            view = "v_" + name.replace("-", "_")
            con.execute(f'CREATE OR REPLACE VIEW "{view}" AS SELECT * FROM read_parquet({file_sql}, union_by_name=true)')
            created.append(view)
        con.execute("CREATE OR REPLACE TABLE _catalog AS SELECT * FROM (VALUES " + ",".join(f"('{v}')" for v in created) + ") t(view_name)" if created else "CREATE OR REPLACE TABLE _catalog(view_name VARCHAR)")
    finally:
        con.close()
    return created
