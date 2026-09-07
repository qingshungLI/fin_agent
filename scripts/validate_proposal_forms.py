"""Prior-only real-model acceptance check: all seven forms, no outcome data."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from engine.audit import write_json
from engine.catalog import build_map
from engine.cycle import initial_tasks, prior_hint
from engine.llm import DeepSeek

def main():
    root = Path("artifacts/validation/form-priors")
    root.mkdir(parents=True, exist_ok=True)
    metas = [json.loads(p.read_text()) for p in Path("artifacts/cache").glob("*/manifest.json")]
    meta = next(m for m in metas if m["identity"]["config"].get("max_symbols") == 0
                and m["identity"]["config"].get("industry_source") == "rqdata_daily")
    fields = {f for f in meta["fields"] if not f.startswith("auction")}
    cuts = json.loads(Path("artifacts/rqdata-full-A-02/cuts.json").read_text())
    client = DeepSeek(Path("artifacts/llm-cache"), max_calls=150)
    cells = build_map()
    def one(pair):
        index, task = pair
        cell = next(c for c in cells if c["family"] == task.family and c["form"] == task.form)
        try:
            structure = client.propose(cell, "form-proof", index, fields, cuts, prior_hint(task, None))
            write_json(root / f"prior-{index:02d}.json", structure.model_dump())
            result = {"index": index, "coordinate": cell["id"], "state": "approved_prior"}
        except (ValueError, KeyError, RuntimeError) as exc:
            result = {"index": index, "coordinate": cell["id"], "state": "rejected", "reason": str(exc)}
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(one, enumerate(initial_tasks()[:9])))
    write_json(root / "report.json", {"results": results, "new_requests": client.calls,
        "outcomes_read": False, "scope": "prior generation, schema and model review; not factor validation"})
    return 0 if all(r["state"] == "approved_prior" for r in results) else 2

if __name__ == "__main__":
    raise SystemExit(main())
