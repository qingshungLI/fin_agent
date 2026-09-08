"""Durable A-only research orchestration; explicit confirmation gate.

A run freezes its code, configuration and proposal before measurement. Checkpoints
are deterministic and verified on resume. A process lock serializes state changes.
"""
import json
import re
import sys
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter

# Windows compatibility: fcntl not available on Windows
if sys.platform != "win32":
    import fcntl
else:
    fcntl = None

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
from engine.continuation import inherit_research, prioritize_queue
from engine.cycle import (
    ProposalTask,
    followup_tasks,
    initial_tasks,
    merge_induction,
    observation_laws,
    prior_hint,
)
from engine.discovery import evolve_operators, repeat_splits, variance_vs_mean_screen
from engine.llm import DeepSeek
from engine.memory import fit_hierarchy, next_probe, reconcile_law_posterior
from engine.metrics import group_returns, measure_panel, power_budget, summarize


class StopRequested(RuntimeError):
    """Signal a user requested graceful stop without converting it into a failed run."""


def control_path(folder: Path) -> Path:
    """Return the sidecar control file for a research batch.

    Args:
        folder: Batch artifact directory.
    Returns:
        Path: Control file path.
    """
    return folder / "control.json"


def read_control(folder: Path) -> dict[str, str]:
    """Read a batch control request, treating an absent file as run.

    Args:
        folder: Batch artifact directory.
    Returns:
        dict[str, str]: Action and optional timestamp metadata.
    """
    path = control_path(folder)
    if not path.is_file():
        return {"action": "run"}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"action": "run"}
    return value if isinstance(value, dict) else {"action": "run"}


def honor_control(folder: Path, state: dict, checkpoint: Path) -> None:
    """Apply pause or stop requests at a safe checkpoint boundary.

    Args:
        folder: Batch artifact directory containing control.json.
        state: Mutable checkpoint state.
        checkpoint: Durable checkpoint path.
    Raises:
        StopRequested: When the operator requests a graceful stop.
    """
    action = read_control(folder).get("action", "run")
    if action == "stop":
        state["status"] = "STOPPED"
        state["stop_reason"] = "Stopped by operator from control panel"
        write_json(checkpoint, state)
        raise StopRequested(state["stop_reason"])
    if action != "pause":
        return
    state["status"] = "PAUSED"
    write_json(checkpoint, state)
    while read_control(folder).get("action", "run") == "pause":
        time.sleep(1.0)
    if read_control(folder).get("action", "run") == "stop":
        state["status"] = "STOPPED"
        state["stop_reason"] = "Stopped by operator from control panel"
        write_json(checkpoint, state)
        raise StopRequested(state["stop_reason"])
    state["status"] = "RUNNING"
    write_json(checkpoint, state)


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
def project_lock(root: Path) -> Iterator[None]:
    """Serialize research writes with a process-owned operating-system lock.

    Args:
        root: Shared local artifact directory used by every research writer.
    Yields:
        None: Exclusive section; assumes a filesystem supporting native locks.
    """
    root.mkdir(parents=True, exist_ok=True)
    # Keep the file so competing writers always lock the same file object.
    with (root / ".run.lock").open("a+b") as handle:
        if fcntl is None:
            import msvcrt

            if handle.seek(0, 2) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Another research writer is running") from exc
        else:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Another research writer is running") from exc
        try:
            yield
        finally:
            if fcntl is None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def eligibility(row, config, report):
    reasons = []
    if config.mode != "formal":
        reasons.append(f"{config.mode} mode")
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


def refresh_memory(rows, folder, config, enabled):
    from engine.memory_inputs import build_memory_inputs
    if not enabled:
        return {"state": "UNIDENTIFIABLE", "terms": [], "reason": "Bayes disabled"}
    frame, covariance, diagnostic = build_memory_inputs(rows, folder, config.n_boot, config.seed)
    write_json(folder / "memory-inputs.json", diagnostic)
    if frame.empty or covariance is None:
        return {"state": "UNIDENTIFIABLE", "terms": [], "reason": diagnostic["state"]}
    frame.to_parquet(folder / "memory-quarters.parquet")
    np.save(folder / "memory-covariance.npy", covariance)
    return fit_hierarchy(frame, config.seed, covariance=covariance)


def run_research(config: ResearchConfig, run_id: str, data_root=Path("data"),
                 output_root=Path("artifacts"), discovery=False, bayes=False):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("Invalid run ID")
    root = Path(output_root).resolve()
    # The central project audit cannot be moved with --output-root.
    audit_root = ROOT / "artifacts"
    with project_lock(audit_root):
        return _run(config, run_id, Path(data_root), root, audit_root, discovery, bayes)


def runtime_identity() -> dict[str, str]:
    """Return installed runtime versions; no arguments, assumes local metadata."""
    from importlib.metadata import PackageNotFoundError, version
    environment = {"python": sys.version.split()[0]}
    for package in ("numpy", "pandas", "scipy", "scikit-learn", "pymc", "pyarrow"):
        try:
            environment[package] = version(package)
        except PackageNotFoundError:
            environment[package] = "not_installed"
    return environment


def finish_pending(state, rows, folder, config, bayes, llm, cells, checkpoint):
    """Replay pending interpretation using committed measurements and fixed IDs.

    Args:
        state: Mutable checkpoint with at most one pending measured structure.
        rows: Verified research results in chronological order.
        folder: Current run directory.
        config: Frozen research configuration.
        bayes: Whether to fit hierarchical memory.
        llm: Cached role client, or None for manual seeds.
        cells: Fixed searchable map.
        checkpoint: Durable state path.
    Returns:
        dict: Updated posterior; a failed hook leaves measurement committed.
    """
    posterior = state.get("posterior", {"state": "UNIDENTIFIABLE", "terms": []})
    sid = state.get("pending_postprocess")
    if sid is None:
        return posterior
    row = next(row for row in rows if row["id"] == sid)
    destination = folder / sid
    if llm and row["blades"]["assertions"]:
        from engine.llm import role_context
        context = role_context("reconciler", structure_id=sid,
            assertion_results=[{"id": a["id"], "state": a["state"]} for a in row["blades"]["assertions"]])
        reconciliation = llm.request("reconciler", context,
            "Return JSON with aligned, divergent and unresolved arrays of assertion IDs only. "
            "hold goes in aligned, violated in divergent, untested in unresolved. "
            "No explanation or causal text.")
        expected = {name: sorted(a["id"] for a in row["blades"]["assertions"] if a["state"] == value)
                    for name, value in [("aligned", "hold"), ("divergent", "violated"),
                                        ("unresolved", "untested")]}
        if {k: sorted(v) for k, v in reconciliation.items()} != expected:
            raise ValueError("Reconciler changed deterministic assertion outcomes")
        row["reconciliation"] = reconciliation
    laws = observation_laws(rows)
    write_json(folder / "laws.json", laws)
    if config.auto_evolve and llm:
        followups = followup_tasks(row, rows, exploratory=config.mode == "fast")
        write_json(destination / "followups.json", followups)
        for payload in reversed(followups["tasks"]):
            task = ProposalTask.model_validate(payload)
            if task.key not in state["queued_keys"]:
                # Keep the cold-start 2x2 intact; then process a resolved follow-up.
                insertion = max(0, 4 - len(rows))
                state["queue"].insert(insertion, payload)
                state["queued_keys"].append(task.key)
        if len(rows) % 5 == 0:
            posterior = refresh_memory(rows, folder, config, bayes)
            state["posterior"] = json_safe(posterior)
            write_json(folder / f"memory-step-{len(rows):03d}.json", json_safe(posterior))
            probe = next_probe(cells, posterior, {f"{r['family']}-F{r['form']}" for r in rows})
            if probe:
                write_json(folder / f"probe-step-{len(rows):03d}.json", {
                    "coordinate": probe["id"], "basis": posterior["state"],
                    "formal": False})
                # Prioritize an existing unexplored seed without duplicating it.
                chosen = next((i for i,t in enumerate(state["queue"])
                               if t["family"]==probe["family"] and t["form"]==probe["form"]
                               and t["operator"]=="seed"), None)
                if chosen is not None:
                    state["queue"].insert(0, state["queue"].pop(chosen))
        if len(rows) % 5 == 0 and laws:
            from engine.llm import role_context
            edits = llm.request("inducer", role_context("inducer", laws=laws, posterior={
                **posterior, "available_coordinates": [c["id"] for c in cells if c["status"] == "unexplored"
                    and not any(r["family"] == c["family"] and r["form"] == c["form"] for r in rows)]}),
                "Return JSON {probes:[],connections:[]}. Probe coordinates must be in available_coordinates. "
                "At most three probes, each "
                "{coordinate:'M1-F1',evidence:[existing law IDs]}; at most five connections "
                "{laws:[existing law IDs],hypothesis:'unconfirmed Chinese research question'}. "
                "Do not rewrite verdicts, frozen vocabulary or claim a law is confirmed. "
                "Prefer empty lists if there is no supported research connection.")
            visited = {f"{r['family']}-F{r['form']}" for r in rows}
            remaining_cells = [{**c, "status": "explored"} if c["id"] in visited else c for c in cells]
            induction = merge_induction(edits, laws, remaining_cells)
            write_json(folder / f"induction-{len(rows):03d}.json", induction)
            for payload in induction["tasks"]:
                task = ProposalTask.model_validate(payload)
                if task.key not in state["queued_keys"]:
                    state["queue"].append(payload)
                    state["queued_keys"].append(task.key)
    write_json(destination / "result.json", row)
    state["artifact_hashes"].update({
        str(p.relative_to(folder)): file_hash(p) for p in destination.iterdir() if p.is_file()
    })
    state["pending_postprocess"] = None
    state["posterior"] = json_safe(posterior)
    write_json(checkpoint, state)
    return posterior


def _run(config, run_id, data_root, root, audit_root, discovery, bayes):
    if config.mode == "fast" and bayes:
        raise ValueError("Fast profile defers Bayesian sampling; pass bayes=False")
    store = AuditStore(audit_root)
    folder = root / run_id
    folder.mkdir(parents=True, exist_ok=True)
    llm = DeepSeek(audit_root / "llm-cache", max_calls=config.llm_max_calls) if config.provider in {"llm", "hybrid"} else None
    environment = runtime_identity()
    identity = {"environment": environment, "config": config.model_dump(), "data_root": str(data_root.resolve()),
                "discovery": discovery, "bayes": bayes,
                "model": llm.configuration_identity() if llm else None,
                "code": {p.name: file_hash(p) for p in sorted((ROOT / "engine").glob("*.py"))},
                "sources": {str(p.relative_to(data_root)): file_hash(p)
                            for p in sorted(data_root.rglob("*.parquet"))}}
    checkpoint = folder / "checkpoint.json"
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text(encoding='utf-8'))
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
        if config.continue_from:
            state.update(inherit_research(root, folder, config.continue_from, identity))
            store.append("research_inherited", {"run_id": run_id, "source": config.continue_from,
                                                "structures": state["inherited"]})
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
            cuts = json.loads(cut_path.read_text(encoding='utf-8'))
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
        rows = [json.loads((folder / sid / "result.json").read_text(encoding='utf-8')) for sid in state.get("inherited", []) + state["completed"]]
        signal_library = []
        fingerprints = set()
        for row in rows:
            fingerprints.add(row["fingerprint"])
            if row["blades"]["placebo"]["state"] == "pass" and row["verdict"] != "FAIL":
                signal_library.append(pd.read_parquet(folder / row["id"] / "research-factor.parquet"))
        cells = build_map()
        if "queue" not in state:
            tasks = initial_tasks(config.initial_cells) if config.initial_cells else initial_tasks()
            state["queue"] = [t.model_dump() for t in tasks]
            state["queued_keys"] = [t.key for t in tasks]
        honor_control(folder, state, checkpoint)
        posterior = finish_pending(state, rows, folder, config, bayes, llm, cells, checkpoint)
        for index in range(state.get("attempts", len(rows)), config.max_structures):
            honor_control(folder, state, checkpoint)
            begin = perf_counter()
            sid = f"S-{run_id}-{index + 1:03d}"
            destination = folder / sid
            destination.mkdir(exist_ok=True)
            spec_path = destination / "proposal.json"
            if spec_path.exists():
                structure = Structure.model_validate(json.loads(spec_path.read_text(encoding='utf-8')))
            else:
                prioritize_queue(state["queue"], config.max_structures - index, len(rows))
                if not state["queue"]:
                    state["stop_reason"] = "finite feasible proposal queue exhausted"
                    break
                write_json(checkpoint, state)
                task = ProposalTask.model_validate(state["queue"][0])
                cell = next(c for c in cells if c["family"] == task.family and c["form"] == task.form)
                parent = next((r for r in rows if r["id"] == task.parent), None)
                if config.provider == "llm" or (config.provider == "hybrid" and index >= 4):
                    try:
                        structure = llm.propose(cell, run_id, index, set(panel.fields), cuts, prior_hint(task, parent))
                    except ValueError as exc:
                        rejection = {"coordinate": cell["id"], "reason": str(exc),
                                     "outcomes_read_for_proposal": False, "attempt": index+1}
                        write_json(destination / "rejected-prior.json", rejection)
                        state.setdefault("rejected_priors", []).append(rejection)
                        state["queue"].pop(0)
                        state["attempts"] = index+1
                        state.setdefault("artifact_hashes", {})[str((destination/"rejected-prior.json").relative_to(folder))] = file_hash(destination/"rejected-prior.json")
                        write_json(checkpoint, state)
                        store.append("prior_rejected", {"run_id": run_id, **rejection})
                        print(f"{sid}: prior rejected; no measurement performed", flush=True)
                        continue
                    except RuntimeError as exc:
                        if config.initial_cells or config.mode != "fast" or "DeepSeek request failed" not in str(exc):
                            raise
                        # Fast RSI protocol records a model crash and continues with a deterministic seed.
                        # Formal mode remains fail-loud; the fallback never receives LLM evidence.
                        fallback = seed_structure(index, run_id)
                        write_json(destination / "llm-crash-fallback.json", {
                            "state": "CRASH_RECORDED", "error": str(exc), "attempt": index + 1,
                            "fallback": "deterministic_seed", "formal": False,
                            "outcomes_read_for_fallback": False})
                        state.setdefault("events", []).append({"stage": "proposal", "state": "crash",
                            "attempt": index + 1, "fallback": "deterministic_seed"})
                        structure = fallback
                        print(f"{sid}: DeepSeek crash recorded; deterministic seed fallback", flush=True)
                elif index < 4:
                    structure = seed_structure(index, run_id)
                else:
                    raise ValueError("Manual provider has four seeds; use llm/hybrid for automated research")
                write_json(spec_path, structure.model_dump())
                write_json(checkpoint, state)
            fingerprint = digest({"expressions": sorted(structure.operational),
                                  "coverage": structure.coverage, "horizon": structure.primary_horizon})
            try:
                if fingerprint in fingerprints and not (
                    structure.lineage.get("operator") == "cross_family"
                    and any(r["id"] == structure.lineage.get("parent") and r["fingerprint"] == fingerprint for r in rows)
                ):
                    raise ValueError("Duplicate factor definition; requires a new proposal, not another test")
                reports = [register_cell(expr, panel.fields, cuts) for expr in structure.operational]
                orientation = check_convergent_orientation(structure, panel.fields, cuts)
            except ValueError as exc:
                # Registration only examines inputs. An invalid candidate consumes
                # one search attempt, never a return test or the rest of the grid.
                rejection = {"coordinate": f"{structure.family}-F{structure.form}",
                             "reason": str(exc), "attempt": index + 1,
                             "stage": "input_registration", "outcomes_read_for_proposal": False}
                write_json(destination / "rejected-prior.json", rejection)
                state.setdefault("rejected_priors", []).append(rejection)
                state["queue"].pop(0)
                state["attempts"] = index + 1
                for path in (spec_path, destination / "rejected-prior.json"):
                    state["artifact_hashes"][str(path.relative_to(folder))] = file_hash(path)
                write_json(checkpoint, state)
                store.append("prior_rejected", {"run_id": run_id, **rejection})
                print(f"{sid}: input registration rejected: {exc}", flush=True)
                continue
            write_json(destination / "registration.json", {"expressions": reports, "orientation": orientation})
            frozen = audit_root / run_id / sid / "frozen.json"
            if not frozen.exists():
                if llm:
                    try:
                        bets = llm.bets(structure)
                    except RuntimeError as exc:
                        if config.initial_cells or config.mode != "fast" or "DeepSeek request failed" not in str(exc):
                            raise
                        bets = {a.id: {"probability": a.prior_p, "created_at": now(),
                                       "source": "fast_crash_fallback"} for a in structure.assertions}
                        write_json(destination / "llm-crash-fallback.json", {
                            "state": "CRASH_RECORDED", "stage": "bettor", "error": str(exc),
                            "fallback": "manual_prior", "formal": False})
                        print(f"{sid}: bettor crash recorded; manual prior fallback", flush=True)
                else:
                    bets = {a.id: {"probability": a.prior_p, "created_at": now(), "source": "manual_prior"}
                            for a in structure.assertions}
                store.freeze(run_id, structure.model_dump(), bets)
            else:
                content = json.loads(frozen.read_text(encoding='utf-8'))
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
                   "research_profile": config.mode,
                   "measurement": measured, "blades": blades, "stability": split_result,
                   "cost": cost, "verdict": blades["verdict"], "formal": False,
                   "seconds": perf_counter() - begin,
                   "timings": {"measurement_seconds": measurement_seconds, "blades_seconds": blades_seconds}}
            discovery_start = perf_counter()
            if blades["placebo"]["state"] == "pass" or config.mode == "fast":
                screen_candidates = candidates[:4] if config.mode == "fast" else candidates
                screened = variance_vs_mean_screen(stored["contribution"], panel.fields, screen_candidates, config)
                if config.mode == "fast":
                    # 有限重采样无力支撑严格多重检验；排序仅分配探索资源，不授予显著性。
                    ranked = sorted(screened.get("rows", []), key=lambda item: (item["mean_p"], item["name"]))
                    screened["exploratory_candidates"] = [item["name"] for item in ranked[:2]]
                row["discovery"] = {"screen": screened,
                    "evolution": evolve_operators(structure, blades["assertions"], [])}
                row["discovery"]["exploratory"] = config.mode == "fast"
                forest_candidates = screened.get("exploratory_candidates", screened["mean_shift"])
                if discovery and forest_candidates:
                    row["discovery"]["forest"] = repeat_splits(panel, stored["signal_0"],
                                                               forest_candidates, cuts, config,
                                                               horizon=structure.primary_horizon)
            else:
                row["discovery"] = {"state": "BLOCKED", "reason": "placebo first; no mechanism interpretation"}
            row["timings"]["discovery_seconds"] = perf_counter() - discovery_start
            row["confirmation"] = eligibility(row, config, panel.report)
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
            if state["queue"]:
                state["queue"].pop(0)
            write_json(folder / "queue.json", {"pending": state["queue"],
                "remaining_measurement_budget": config.max_structures - index - 1})
            fingerprints.add(fingerprint)
            if blades["placebo"]["state"] == "pass" and row["verdict"] != "FAIL":
                signal_library.append(stored["signal_0"])
            state.setdefault("artifact_hashes", {}).update({
                str(p.relative_to(folder)): file_hash(p) for p in destination.iterdir() if p.is_file()
            })
            state["completed"].append(sid)
            state["attempts"] = index+1
            state["pending_postprocess"] = sid
            write_json(checkpoint, state)
            posterior = finish_pending(state, rows, folder, config, bayes, llm, cells, checkpoint)
            write_json(folder / "queue.json", {"pending": state["queue"],
                "remaining_measurement_budget": config.max_structures - index - 1})
            store.append("structure_completed", {"run_id": run_id, "id": sid,
                                                 "result_hash": digest(row)})
            print(f"{sid}: {row['verdict']} IC={primary['mean']} "
                  f"placebo={blades['placebo']['state']} {row['seconds']:.1f}s", flush=True)
            publish(root, folder, rows, panel, state, store)
        write_json(folder / "consistency.json", consistency_views(rows))
        posterior = refresh_memory(rows, folder, config, bayes)
        state["posterior"] = json_safe(posterior)
        write_json(folder / "memory.json", json_safe(posterior))
        write_json(folder / "wealth.json", {"state": "UNCALIBRATED",
            "reason": "IC placebo distributions do not supply per-assertion p0 bounds; no fabricated wealth",
            "formal_decision_role": "none"})
        calibration = []
        for row in rows:
            origin_run = state.get("source_runs", {}).get(row["id"], run_id)
            frozen = json.loads((audit_root / origin_run / row["id"] / "frozen.json").read_text(encoding="utf-8"))
            for assertion in row["blades"]["assertions"]:
                if assertion["state"] in {"hold", "violated"}:
                    calibration.append({"structure": row["id"], "assertion": assertion["id"],
                        "probability": frozen["bets"][assertion["id"]]["probability"],
                        "outcome": int(assertion["state"] == "hold")})
        from engine.evidence import calibration_report
        write_json(folder / "blind-calibration.json", {
            "observations": calibration,
            "reliability": calibration_report([r["probability"] for r in calibration],
                                              [r["outcome"] for r in calibration]),
            "platt_fitted": False,
            "reason": "same-model assertions share data; no claim of independent calibration"})
        write_json(folder / "portfolio.json", {"state": "BLOCKED", "formal_structures": [],
            "reason": "No B-confirmed PASS structures; unconfirmed laws cannot route positions"})
        write_json(folder / "memory-gaps.json", reconcile_law_posterior(observation_laws(rows), posterior))
        state.setdefault("artifact_hashes", {}).update({
            p.name: file_hash(p) for p in folder.glob("*.json") if p.name not in {"checkpoint.json", "failure.json", "progress.json"}
        })
        state["status"] = "COMPLETED"
        if (root / "failure.json").exists():
            previous = json.loads((root / "failure.json").read_text(encoding='utf-8'))
            write_json(folder / "previous-failure.json", previous)
            (root / "failure.json").unlink()
        state["finished_at"] = now()
        state["timings"]["total_seconds"] = perf_counter() - started
        state["confirmation"] = {"eligible_ids": [r["id"] for r in rows if r["confirmation"]["eligible"] and r["id"] in state["completed"]],
                                 "B_read": False, "H_read": False}
        write_json(checkpoint, state)
        store.append("run_completed", {"run_id": run_id, "checkpoint_hash": digest(state)})
        publish(root, folder, rows, panel, state, store)
        return state
    except StopRequested as exc:
        state["status"] = "STOPPED"
        state["stop_reason"] = str(exc)
        state["finished_at"] = now()
        write_json(checkpoint, state)
        store.append("run_stopped", {"run_id": run_id, "reason": str(exc)})
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
    from collections import Counter
    progress = {"attempts": state.get("attempts", 0), "budget": state["identity"]["config"]["max_structures"],
                "new_measured": len(state["completed"]), "inherited": len(state.get("inherited", [])),
                "rejected": len(state.get("rejected_priors", [])),
                "pending": dict(Counter(t["operator"] for t in state.get("queue", []))),
                "measured_operators": dict(Counter(r["structure"]["lineage"].get("operator", "seed") for r in rows)),
                "unique_measured_cells": len({(r["family"], r["form"]) for r in rows})}
    write_json(folder / "progress.json", progress)
    overview = {"progress": progress, "run_id": state["run_id"], "status": state["status"], "map": cells,
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
