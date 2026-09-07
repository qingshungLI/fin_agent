"""Durable A-only research orchestration; explicit confirmation gate.

A run freezes its code, configuration and proposal before measurement. Checkpoints
are deterministic and verified on resume. A process lock serializes state changes.
"""
import fcntl
import json
import re
import traceback
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from engine.audit import AuditStore, digest, now, write_json
from engine.blades import run_blades
from engine.cache import cached_panel, file_hash
from engine.catalog import (
    Structure,
    build_map,
    check_convergent_orientation,
    freeze_cuts,
    register_cell,
    seed_structure,
)
from engine.config import ROOT, ResearchConfig
from engine.consistency import consistency_views
from engine.discovery import evolve_operators, repeat_splits, variance_vs_mean_screen
from engine.llm import DeepSeek
from engine.memory import fit_hierarchy, reconcile_law_posterior
from engine.metrics import group_returns, measure_panel, power_budget, summarize


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


@contextmanager
def project_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".run.lock").open("a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another research writer is running") from exc
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def eligibility(row, config, report):
    reasons = []
    if config.mode != "formal":
        reasons.append("engineering mode")
    if any(r.get("formal_eligible") is False or r.get("status") == "fail" for r in report):
        reasons.append("unresolved source-data quality")
    b = row["blades"]
    if b["placebo"]["state"] != "pass":
        reasons.append("placebo not passed")
    if not b["assertions"] or any(a["state"] != "hold" for a in b["assertions"]):
        reasons.append("necessary assertions unresolved or contradicted")
    if b["increment"]["state"] not in {"pass", "not_applicable"}:
        reasons.append("increment unresolved")
    if not row["stability"]["consistent"]:
        reasons.append("A-fold instability")
    if row["cost"]["net_top_excess_mean"] is None or row["cost"]["net_top_excess_mean"] <= 0:
        reasons.append("fixed-cost top-group excess return not positive")
    return {"eligible": not reasons, "reasons": reasons, "formal": False}


def stability(stored, structure, config):
    series = stored[f"ic_e1_h{structure.primary_horizon}"].ic
    rows = []
    # Five predetermined chronological A folds; endpoints truncated for overlap.
    for i, positions in enumerate(np.array_split(np.arange(len(series)), 5)):
        sequence = series.iloc[positions].copy()
        sequence.iloc[-(structure.primary_horizon + 1):] = np.nan
        rows.append({"fold": i, **summarize(sequence, structure.primary_horizon, config)})
    return {"segment": "A_internal_only", "folds": rows,
            "consistent": all(r["mean"] is not None and r["mean"] > 0 for r in rows)}


def cost_report(stored, panel, structure):
    h = structure.primary_horizon
    signal = stored["signal_0"]
    net = group_returns(signal, panel.labels[f"net_{h}"])
    raw = group_returns(signal, panel.labels[f"raw_{h}"])
    return json_safe({"horizon": h, "net_top_mean": net.Q5.mean(),
            "raw_top_mean": raw.Q5.mean(), "net_tb": (net.Q5 - net.Q1).mean(),
            "net_top_excess_mean": (net.Q5 - panel.labels[f"raw_{h}"].mean(axis=1)).mean(),
            "interpretation": "fixed-cost overlapping research groups; not executable strategy returns"})


def run_research(config: ResearchConfig, run_id: str, data_root=Path("data"),
                 output_root=Path("artifacts"), discovery=False, bayes=False):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("Invalid run ID")
    root = Path(output_root).resolve()
    # The central project audit cannot be moved with --output-root.
    audit_root = ROOT / "artifacts"
    with project_lock(audit_root):
        return _run(config, run_id, Path(data_root), root, audit_root, discovery, bayes)


def _run(config, run_id, data_root, root, audit_root, discovery, bayes):
    store = AuditStore(audit_root)
    folder = root / run_id
    folder.mkdir(parents=True, exist_ok=True)
    identity = {"config": config.model_dump(), "data_root": str(data_root.resolve()),
                "discovery": discovery, "bayes": bayes,
                "code": {p.name: file_hash(p) for p in sorted((ROOT / "engine").glob("*.py"))},
                "sources": {str(p.relative_to(data_root)): file_hash(p)
                            for p in sorted(data_root.rglob("*.parquet"))}}
    checkpoint = folder / "checkpoint.json"
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        if state["identity"] != identity:
            raise ValueError("Resume requires unchanged configuration and implementation; use a new run ID")
        store.verify()
        for relative, expected in state.get("artifact_hashes", {}).items():
            if file_hash(folder / relative) != expected:
                raise ValueError("Checkpoint artifact was modified: " + relative)
        if state["status"] == "COMPLETED":
            return state
    else:
        state = {"identity": identity, "run_id": run_id, "status": "RUNNING",
                 "completed": [], "started_at": now(), "timings": {}}
        store.append("run_started", {"run_id": run_id, "identity_hash": digest(identity)})
        write_json(checkpoint, state)
    started = perf_counter()
    write_json(root / "overview.json", {"run_id": run_id, "status": "STARTING", "map": build_map(),
        "message": "正在加载与验证探索段数据；B/H保持封存"})
    write_json(root / "structures.json", [])
    try:
        store.append("A_data_read", {"run_id": run_id, "start": config.start, "end": config.end,
                                     "policy": config.industry_policy})
        panel, hit = cached_panel(data_root, config, audit_root / "cache")
        state["timings"]["panel_seconds"] = perf_counter() - started
        state["cache_hit"] = hit
        write_json(folder / "data-quality.json", panel.report)
        print(f"panel ready {panel.fields['close'].shape}, cache={hit}", flush=True)
        publish(root, folder, [], panel, state, store)
        candidates = ["market_cap_pct", "amihud_pct", "realized_vol_pct",
                      "turnover_today_pct", "avg_trade_size_pct"]
        cut_path = folder / "cuts.json"
        if cut_path.exists():
            cuts = json.loads(cut_path.read_text())
        else:
            training = {k: v.iloc[:int(len(v) * .65)] for k, v in panel.fields.items()}
            cuts = freeze_cuts(training, candidates, config.seed)
            write_json(cut_path, cuts)
            store.append("cuts_frozen", {"run_id": run_id, "hash": digest(cuts),
                                         "source": "first 65 percent of A dates; no returns"})
        state.setdefault("artifact_hashes", {}).update({
            "cuts.json": file_hash(cut_path),
            "data-quality.json": file_hash(folder / "data-quality.json"),
        })
        write_json(checkpoint, state)
        llm = DeepSeek(audit_root / "llm-cache") if config.provider in {"llm", "hybrid"} else None
        rows = [json.loads((folder / sid / "result.json").read_text()) for sid in state["completed"]]
        signal_library = []
        fingerprints = set()
        for row in rows:
            fingerprints.add(row["fingerprint"])
            if row["blades"]["placebo"]["state"] == "pass" and row["verdict"] != "FAIL":
                signal_library.append(pd.read_parquet(folder / row["id"] / "research-factor.parquet"))
        cells = build_map()
        order = [("M2", 3), ("M2", 1), ("M1", 3), ("M1", 1)]
        order += [(x["family"], x["form"]) for x in cells
                  if x["status"] == "unexplored" and (x["family"], x["form"]) not in order]
        for index in range(len(rows), config.max_structures):
            begin = perf_counter()
            sid = f"S-{run_id}-{index + 1:03d}"
            destination = folder / sid
            destination.mkdir(exist_ok=True)
            spec_path = destination / "proposal.json"
            if spec_path.exists():
                structure = Structure.model_validate(json.loads(spec_path.read_text()))
            else:
                family, form = order[index]
                cell = next(c for c in cells if c["family"] == family and c["form"] == form)
                if config.provider == "llm":
                    structure = llm.propose(cell, run_id, index, set(panel.fields))
                elif index < 4:
                    structure = seed_structure(index, run_id)
                else:
                    raise ValueError("Manual/hybrid provider has four vetted seeds; use --provider llm for expansion")
                write_json(spec_path, structure.model_dump())
            fingerprint = digest({"expressions": sorted(structure.operational),
                                  "coverage": structure.coverage, "horizon": structure.primary_horizon})
            if fingerprint in fingerprints:
                raise ValueError("Duplicate factor definition; requires a new proposal, not another test")
            reports = [register_cell(expr, panel.fields, cuts) for expr in structure.operational]
            orientation = check_convergent_orientation(structure, panel.fields, cuts)
            write_json(destination / "registration.json", {"expressions": reports, "orientation": orientation})
            frozen = audit_root / run_id / sid / "frozen.json"
            if not frozen.exists():
                bets = llm.bets(structure) if llm else {
                    a.id: {"probability": a.prior_p, "created_at": now(), "source": "manual_prior"}
                    for a in structure.assertions}
                store.freeze(run_id, structure.model_dump(), bets)
            else:
                content = json.loads(frozen.read_text())
                if content["structure"] != structure.model_dump():
                    raise ValueError("Frozen proposal differs from resume input")
            store.append("measurement_started", {"run_id": run_id, "id": sid})
            measurement_start = perf_counter()
            measured, stored = measure_panel(structure, panel, config, cuts)
            measurement_seconds = perf_counter() - measurement_start
            write_json(destination / "measurement.json", json_safe(measured))
            print(f"{sid}: measurement ready in {measurement_seconds:.1f}s; starting placebo", flush=True)
            blades_start = perf_counter()
            blades = run_blades(structure, panel, measured, stored, signal_library, config)
            blades_seconds = perf_counter() - blades_start
            split_result = stability(stored, structure, config)
            cost = cost_report(stored, panel, structure)
            row = {"id": sid, "name": structure.name, "family": structure.family, "form": structure.form,
                   "structure": structure.model_dump(), "fingerprint": fingerprint,
                   "measurement": measured, "blades": blades, "stability": split_result,
                   "cost": cost, "verdict": blades["verdict"], "formal": False,
                   "seconds": perf_counter() - begin,
                   "timings": {"measurement_seconds": measurement_seconds, "blades_seconds": blades_seconds}}
            discovery_start = perf_counter()
            if blades["placebo"]["state"] == "pass":
                screened = variance_vs_mean_screen(stored["contribution"], panel.fields, candidates, config)
                row["discovery"] = {"screen": screened,
                    "evolution": evolve_operators(structure, blades["assertions"], [])}
                if discovery and screened["mean_shift"]:
                    row["discovery"]["forest"] = repeat_splits(panel, stored["signal_0"],
                                                               screened["mean_shift"], cuts, config)
            else:
                row["discovery"] = {"state": "BLOCKED", "reason": "placebo first; no mechanism interpretation"}
            row["timings"]["discovery_seconds"] = perf_counter() - discovery_start
            row["confirmation"] = eligibility(row, config, panel.report)
            if llm and blades["assertions"]:
                from engine.llm import role_context
                context = role_context("reconciler", structure_id=sid,
                    assertion_results=[{"id": a["id"], "state": a["state"]} for a in blades["assertions"]])
                reconciliation = llm.request("reconciler", context,
                    "Return JSON with aligned, divergent and unresolved arrays of assertion IDs only. "
                    "hold goes in aligned, violated in divergent, untested in unresolved. "
                    "No explanation or causal text.")
                expected = {name: sorted(a["id"] for a in blades["assertions"] if a["state"] == value)
                            for name, value in [("aligned", "hold"), ("divergent", "violated"),
                                                ("unresolved", "untested")]}
                if {k: sorted(v) for k, v in reconciliation.items()} != expected:
                    raise ValueError("Reconciler changed deterministic assertion outcomes")
                row["reconciliation"] = reconciliation
            # Always export research factors, clearly distinguished from formal cards.
            stored["signal_0"].to_parquet(destination / "research-factor.parquet")
            stored["contribution"].to_parquet(destination / "contribution.parquet")
            pd.concat({key: value.ic for key, value in stored.items() if key.startswith("ic_e")},
                      axis=1).to_parquet(destination / "daily-ic.parquet")
            primary = next(r for r in measured["curves"] if r["expression"] == 1
                           and r["horizon"] == structure.primary_horizon)
            row["power"] = power_budget(primary["n_eff"]) if primary["n_eff"] else None
            row["seconds"] = perf_counter() - begin
            row = json_safe(row)
            write_json(destination / "result.json", row)
            rows.append(row)
            fingerprints.add(fingerprint)
            if blades["placebo"]["state"] == "pass" and row["verdict"] != "FAIL":
                signal_library.append(stored["signal_0"])
            state.setdefault("artifact_hashes", {}).update({
                str(p.relative_to(folder)): file_hash(p) for p in destination.iterdir() if p.is_file()
            })
            state["completed"].append(sid)
            write_json(checkpoint, state)
            store.append("structure_completed", {"run_id": run_id, "id": sid,
                                                 "result_hash": digest(row)})
            print(f"{sid}: {row['verdict']} IC={primary['mean']} "
                  f"placebo={blades['placebo']['state']} {row['seconds']:.1f}s", flush=True)
            publish(root, folder, rows, panel, state, store)
        write_json(folder / "consistency.json", consistency_views(rows))
        # Only non-artifact, non-retracted structures enter hierarchical memory.
        quarters = []
        for row in rows:
            if row["blades"]["placebo"]["state"] != "pass" or any(
                a["kind"] == "side" and a["state"] == "violated" for a in row["blades"]["assertions"]):
                continue
            for q in row["measurement"]["quarterly"]:
                if q["mean"] is not None and q["se"] is not None:
                    quarters.append({"structure": row["id"], "period": q["period"],
                                     "family": row["family"], "form": str(row["form"]),
                                     "mean": q["mean"], "se": q["se"]})
        if bayes and quarters:
            posterior = fit_hierarchy(pd.DataFrame(quarters), config.seed)
        else:
            posterior = {"state": "UNIDENTIFIABLE", "terms": [],
                         "reason": "no eligible quarterly structures" if not quarters else "Bayes disabled"}
        write_json(folder / "memory.json", json_safe(posterior))
        write_json(folder / "wealth.json", {"state": "UNCALIBRATED",
            "reason": "IC placebo distributions do not supply per-assertion p0 bounds; no fabricated wealth",
            "formal_decision_role": "none"})
        calibration = []
        for row in rows:
            frozen = json.loads((audit_root / run_id / row["id"] / "frozen.json").read_text())
            for assertion in row["blades"]["assertions"]:
                if assertion["state"] in {"hold", "violated"}:
                    calibration.append({"structure": row["id"], "assertion": assertion["id"],
                        "probability": frozen["bets"][assertion["id"]]["probability"],
                        "outcome": int(assertion["state"] == "hold")})
        write_json(folder / "blind-calibration.json", {"observations": calibration,
            "platt_fitted": False, "reason": "insufficient independent resolved observations"})
        write_json(folder / "portfolio.json", {"state": "BLOCKED", "formal_structures": [],
            "reason": "No B-confirmed PASS structures; unconfirmed laws cannot route positions"})
        write_json(folder / "memory-gaps.json", reconcile_law_posterior([], posterior))
        state["status"] = "COMPLETED"
        if (root / "failure.json").exists():
            previous = json.loads((root / "failure.json").read_text())
            write_json(folder / "previous-failure.json", previous)
            (root / "failure.json").unlink()
        state["finished_at"] = now()
        state["timings"]["total_seconds"] = perf_counter() - started
        state["confirmation"] = {"eligible_ids": [r["id"] for r in rows if r["confirmation"]["eligible"]],
                                 "B_read": False, "H_read": False}
        write_json(checkpoint, state)
        store.append("run_completed", {"run_id": run_id, "checkpoint_hash": digest(state)})
        publish(root, folder, rows, panel, state, store)
        return state
    except BaseException as exc:
        state["status"] = "FAILED"
        write_json(checkpoint, state)
        failure = {"run_id": run_id, "error": str(exc), "type": type(exc).__name__,
                   "traceback": traceback.format_exc(), "timestamp": now()}
        write_json(folder / "failure.json", failure)
        write_json(root / "failure.json", failure)
        write_json(root / "overview.json", {"run_id": run_id, "status": "FAILED",
            "map": build_map(), "message": failure["error"],
            "report": [{"name": failure["error"], "status": "fail", "count": 1}]})
        store.append("run_failed", {"run_id": run_id, "error_type": type(exc).__name__})
        raise


def publish(root, folder, rows, panel, state, store):
    cells = build_map()
    for cell in cells:
        matched = [r for r in rows if r["family"] == cell["family"] and r["form"] == cell["form"]]
        if matched:
            cell["research_status"] = matched[-1]["verdict"]
            cell["structures"] = [r["id"] for r in matched]
    overview = {"run_id": state["run_id"], "status": state["status"], "map": cells,
                "report": panel.report, "dates": len(panel.dates),
                "symbols": len(panel.fields["close"].columns), "audit": store.verify(),
                "power": rows[0]["power"] if rows else None,
                "message": "研究输出；尚未使用B/H，不代表正式通过",
                "timings": state["timings"]}
    write_json(root / "overview.json", json_safe(overview))
    write_json(root / "structures.json", rows)
    text = ["# AutoAlpha research report", "", f"Run: {state['run_id']}", "",
            "All results below are exploratory A-segment evidence, not confirmed factors.",
            "B and H remain unread. Unresolved data quality prevents formal promotion.", "",
            "| Structure | IC | Placebo | Provisional |", "|---|---:|---|---|"]
    laws = ["# law.md", "", "Unconfirmed observations only. No trading routing permission.", ""]
    for row in rows:
        primary = next(x for x in row["measurement"]["curves"] if x["expression"] == 1
                       and x["horizon"] == row["structure"]["primary_horizon"])
        text.append(f"| {row['name']} | {primary['mean']} | {row['blades']['placebo']['state']} | {row['verdict']} |")
        text += ["", f"Factor file: {row['id']}/research-factor.parquet",
                 "Promotion blockers: " + ", ".join(row["confirmation"]["reasons"]), ""]
        if row["blades"]["placebo"]["state"] == "pass":
            for assertion in row["blades"]["assertions"]:
                laws += [(f"- {row['id']}.{assertion['id']}: {assertion['subject']} = {assertion['state']}. "
                          "Scope: A, known-industry cohort. Confirmed: false. Reopen: independent confirmation."), ""]
    (folder / "report.md").write_text("\n".join(text), encoding="utf-8")
    (folder / "law.md").write_text("\n".join(laws), encoding="utf-8")
