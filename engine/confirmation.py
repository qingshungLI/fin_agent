"""One-shot B/H evaluation. Admission is checked before any segment is read."""
import json
import re
from pathlib import Path

from engine.audit import AuditStore, digest, write_json
from engine.blades import blade_assertion
from engine.catalog import Structure
from engine.config import CONFIRM_END, CONFIRM_START, HOLDOUT_END, HOLDOUT_START, ROOT
from engine.data import build_panel
from engine.discovery import blade_icm, make_sample
from engine.metrics import holm, measure_panel
from engine.pipeline import eligibility, json_safe, project_lock


def batch_decisions(rows, alpha=.05):
    adjusted = holm([row["p"] for row in rows])
    decisions = []
    for row, p in zip(rows, adjusted):
        hold = all(a["state"] == "hold" for a in row["assertions"]) and bool(row["assertions"])
        contradicted = any(a["state"] == "violated" for a in row["assertions"])
        verdict = ("PASS" if hold and p <= alpha else "FAIL" if contradicted else "UNDECIDABLE")
        decisions.append({**row, "adjusted_p": p, "verdict": verdict,
                          "formal": verdict == "PASS", "correction": "frozen-batch Holm"})
    return decisions


def confirm_once(config, run_id, ids, data_root=Path("data"), output_root=Path("artifacts"), segment="B"):
    if segment not in {"B", "H"} or not ids or len(ids) != len(set(ids)):
        raise ValueError("A nonempty unique B/H batch is required")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id) or any(
        not re.fullmatch(r"S-[A-Za-z0-9-]+", sid) for sid in ids):
        raise ValueError("Invalid run or structure ID")
    root = Path(output_root).resolve()
    folder = root / run_id
    store = AuditStore(ROOT / "artifacts")
    with project_lock(ROOT / "artifacts"):
        state = json.loads((folder / "checkpoint.json").read_text())
        if state["status"] != "COMPLETED" or state["identity"]["config"] != config.model_dump():
            raise ValueError("Only a completed unchanged exploratory run can be confirmed")
        from engine.cache import file_hash
        if not set(ids) <= set(state["completed"]):
            raise ValueError("Batch contains structures outside the completed run")
        current_code = {p.name: file_hash(p) for p in sorted((ROOT / "engine").glob("*.py"))}
        current_sources = {str(p.relative_to(data_root)): file_hash(p)
                           for p in sorted(Path(data_root).rglob("*.parquet"))}
        if (state["identity"]["code"] != current_code
                or state["identity"]["sources"] != current_sources
                or state["identity"]["data_root"] != str(Path(data_root).resolve())):
            raise ValueError("Research provenance changed; B/H remains unread")
        for relative, expected in state.get("artifact_hashes", {}).items():
            if file_hash(folder / relative) != expected:
                raise ValueError("Research artifact changed; B/H remains unread")
        calibration = ROOT / "artifacts" / "validation" / "calibration.json"
        if not calibration.exists() or not json.loads(calibration.read_text()).get("passed"):
            raise ValueError("Statistical simulation gate not passed; B/H remains unread")
        validation = json.loads(calibration.read_text())
        if any(file_hash(ROOT / "engine" / name) != expected
               for name, expected in validation.get("code_sha256", {}).items()) or not validation.get("code_sha256"):
            raise ValueError("Calibration does not match current inference code; B/H remains unread")
        quality = json.loads((folder / "data-quality.json").read_text())
        rows = [json.loads((folder / sid / "result.json").read_text()) for sid in ids]
        for row in rows:
            check = eligibility(row, config, quality)
            if not check["eligible"]:
                raise ValueError(f"Not eligible: {row['id']}: {check['reasons']}; B/H remains unread")
        if segment == "H":
            previous = json.loads((folder / "confirmation-B.json").read_text())
            passing = {r["id"] for r in previous if r["formal"] and r["verdict"] == "PASS"}
            if not set(ids) <= passing:
                raise ValueError("Holdout requires B-confirmed structures")
        store.verify()
        store.consume(segment, run_id, ids)
        # The access fact survives loading, calculation or publication failures.
        start, end = ((CONFIRM_START, CONFIRM_END) if segment == "B"
                      else (HOLDOUT_START, HOLDOUT_END))
        try:
            panel = build_panel(data_root, config, start=start, end=end)
            if any(r.get("formal_eligible") is False or r["status"] == "fail" for r in panel.report):
                raise ValueError("Confirmation data gate failed")
            cuts = json.loads((folder / "cuts.json").read_text())
            results = []
            for row in rows:
                structure = Structure.model_validate(row["structure"])
                measurement, stored = measure_panel(structure, panel, config, cuts)
                primary = next(r for r in measurement["curves"] if r["expression"] == 1
                               and r["horizon"] == structure.primary_horizon)
                assertions = blade_assertion(structure, panel, stored, config)
                p = primary["p"]
                interaction = None
                if structure.lineage.get("origin") == "forest":
                    moderator = structure.lineage["moderator"]
                    cut = cuts[structure.lineage["cut_id"]]["value"]
                    sample = make_sample(panel, stored["signal_0"], structure.primary_horizon, [moderator])
                    interaction = blade_icm(sample, moderator, cut, structure.primary_horizon, config)
                    p = max(p, interaction["p"])
                results.append({"id": row["id"], "segment": segment, "p": p,
                                "assertions": assertions, "measurement": measurement, "icm": interaction})
            results = json_safe(batch_decisions(results))
            write_json(folder / f"confirmation-{segment}.json", results)
            store.append("confirmation_completed", {"run_id": run_id, "segment": segment,
                                                     "result_hash": digest(results)})
            return results
        except BaseException as exc:
            store.append("confirmation_invalid", {"run_id": run_id, "segment": segment,
                                                   "error_type": type(exc).__name__})
            raise
