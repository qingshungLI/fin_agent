"""Bounded research queue and machine-readable law records.

Only prior specifications and moderator names cross into proposal contexts.
Measurements determine whether a task is enqueued, never a requested direction.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from engine.audit import digest
from engine.catalog import FAMILIES, build_map


class ProposalTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    family: str
    form: int = Field(ge=1, le=7)
    operator: Literal["seed", "horizontal", "cross_family", "forest", "crossover", "probe", "condition", "reverse", "interaction"] = "seed"
    parent: str | None = None
    moderator: str | None = None
    donor: str | None = None
    depth: int = Field(default=0, ge=0, le=2)
    gates: list[dict[str, str]] = Field(default_factory=list, max_length=4)
    orientation: Literal[-1, 1] = 1
    evidence_basis: str | None = None

    @model_validator(mode="after")
    def validate_evolution(self):
        if self.operator in {"condition", "reverse", "interaction"} and not self.parent:
            raise ValueError("An evolved hypothesis requires a parent")
        if self.operator == "interaction" and (not self.donor or self.donor == self.parent):
            raise ValueError("Interaction requires a distinct donor")
        if self.operator == "condition" and not self.gates:
            raise ValueError("Conditional evolution requires frozen gates")
        for gate in self.gates:
            if set(gate) != {"field", "cut_id", "branch"} or gate["branch"] not in {"low", "high"}:
                raise ValueError("Invalid frozen gate")
        return self

    @property
    def key(self):
        return digest(self.model_dump())


def initial_tasks(coordinates: tuple[str, ...] = ()) -> list[ProposalTask]:
    """Factorial start, then cover all seven feasible forms before filling rows."""
    ordered = [("M2", 3), ("M2", 1), ("M1", 3), ("M1", 1),
               ("M1", 2), ("M4", 4), ("M10", 5), ("M2", 6), ("M5", 7)]
    ordered += [(cell["family"], cell["form"]) for cell in build_map()
                if cell["status"] == "unexplored"]
    seen, result = set(), []
    for pair in ordered:
        if pair not in seen:
            result.append(ProposalTask(family=pair[0], form=pair[1]))
            seen.add(pair)
    if coordinates:
        available = {f"{task.family}-F{task.form}": task for task in result}
        unknown = set(coordinates) - set(available)
        if unknown or len(set(coordinates)) != len(coordinates):
            raise ValueError("Unknown or duplicated initial research cells")
        return [available[key] for key in coordinates]
    return result


def followup_tasks(row: dict[str, Any], history: list[dict[str, Any]],
                   maximum_depth: int = 2, *, exploratory: bool = False) -> dict[str, Any]:
    """Generate bounded new hypotheses, preserving untested versus contradicted."""
    structure = row["structure"]
    depth = int(structure["lineage"].get("depth", 0))
    heterogeneous = bool(row.get("discovery", {}).get("forest", {}).get("training_rules"))
    signed_candidate = bool(row.get("directionality", {}).get("reverse_candidate"))
    if row["blades"]["placebo"]["state"] != "pass" and not exploratory and not (heterogeneous or signed_candidate):
        return {"tasks": [], "stop": "artifact gate; no mechanism revision"}
    if depth >= maximum_depth:
        return {"tasks": [], "stop": "frozen lineage depth budget exhausted"}
    power = row.get("power") or {}
    if power.get("main_mde", 1) > 0.05 and not exploratory and not (heterogeneous or signed_candidate):
        return {"tasks": [], "stop": "insufficient power; reopen with more independent dates"}
    family, form = structure["family"], structure["form"]
    available = {(c["family"], c["form"]) for c in build_map() if c["status"] == "unexplored"}
    ancestors = {r["id"] for r in history if r["family"] == family and r["form"] == form}
    tasks = []
    # Heterogeneity and signed hypotheses precede representation changes.
    forest = row.get("discovery", {}).get("forest", {})
    rules = forest.get("training_rules", [])
    selected_rules = []
    for direction in (-1, 1):
        candidate = next((rule for rule in rules if rule["orientation"] == direction), None)
        if candidate is not None:
            selected_rules.append(candidate)
    for rule in rules:
        if len(selected_rules) >= 2:
            break
        if rule not in selected_rules:
            selected_rules.append(rule)
    for rule in selected_rules:
        tasks.append(ProposalTask(family=family, form=6, operator="condition",
            parent=row["id"], moderator=rule["gates"][0]["field"], gates=rule["gates"],
            orientation=rule["orientation"], depth=depth + 1,
            evidence_basis="training_only_condition; independent confirmation required"))
    if row.get("directionality", {}).get("reverse_candidate"):
        tasks.append(ProposalTask(family=family, form=form, operator="reverse",
            parent=row["id"], orientation=-1, depth=depth + 1,
            evidence_basis="two_sided_training_effect; independent confirmation required"))
    if rules:
        for donor in history:
            donor_rules = donor.get("discovery", {}).get("forest", {}).get("training_rules", [])
            if (donor["id"] != row["id"] and donor["family"] != family and donor_rules
                    and donor["structure"]["primary_horizon"] == structure["primary_horizon"]):
                tasks.append(ProposalTask(family=family, form=5, operator="interaction",
                    parent=row["id"], donor=donor["id"], depth=depth + 1,
                    evidence_basis="two heterogeneous components; joint mechanism is a hypothesis"))
                break
    if tasks:
        return {"exploratory": True, "tasks": [t.model_dump() for t in tasks[:4]],
                "stop": None, "objective": "heterogeneity_and_evolution"}
    assertions = row["blades"]["assertions"]
    horizontal = any(a["kind"] in ("shape", "sign") and a["state"] == "violated"
                     for a in assertions) or row["measurement"].get("coverage", 1) < .1
    if horizontal:
        tried = {r["form"] for r in history if r["family"] == family}
        candidate = next((f for f in (1, 3, 5, 2, 4, 7) if f not in tried
                          and (family, f) in available), None)
        if candidate:
            tasks.append(ProposalTask(family=family, form=candidate, operator="horizontal",
                                      parent=row["id"], depth=depth + 1))
    if not tasks and any(a["kind"] == "side" and a["state"] == "violated" for a in assertions):
        # The model chooses a rival from the map using the frozen prior, not effect readings.
        rivals = [f[0] for f in FAMILIES if f[0] != family and (f[0], form) in available]
        for rival in rivals:
            if not any(r["family"] == rival and r["structure"]["lineage"].get("parent") in ancestors
                       for r in history):
                tasks.append(ProposalTask(family=rival, form=form, operator="cross_family",
                                          parent=row["id"], depth=depth + 1))
                break
    forest = row.get("discovery", {}).get("forest", {})
    if not tasks and forest.get("p_median", 1) < .05 and (family, 6) in available:
        names = sorted(k for k, v in forest.get("selection_frequency", {}).items() if v >= .7)
        if names:
            tasks.append(ProposalTask(family=family, form=6, operator="forest",
                                      parent=row["id"], moderator=names[0], depth=depth + 1))
    if not tasks and (family, 6) in available:
        for donor in history:
            donor_spec = donor["structure"]
            moderator = donor_spec.get("lineage", {}).get("moderator")
            if (donor["id"] == row["id"] or donor["family"] == family or not moderator
                    or donor["blades"]["placebo"]["state"] != "pass"
                    or donor.get("verdict") == "FAIL"):
                continue
            supported = any(a["kind"] == "side" and a.get("subject") == moderator
                            and a["state"] == "hold" for a in donor["blades"]["assertions"])
            if supported:
                tasks.append(ProposalTask(family=family, form=6, operator="crossover",
                                          parent=row["id"], donor=donor["id"],
                                          moderator=moderator, depth=depth + 1))
                break
    if not tasks and exploratory:
        # Fast children are proposed hypotheses, never evidence for a mechanism law.
        tried = {r["form"] for r in history if r["family"] == family}
        candidate = next((f for f in (1, 3, 5, 2, 4, 6, 7)
                          if f not in tried and (family, f) in available), None)
        if candidate:
            tasks.append(ProposalTask(family=family, form=candidate, operator="horizontal",
                                      parent=row["id"], depth=depth + 1))
    return {"exploratory": exploratory, "tasks": [t.model_dump() for t in tasks[:1]],
            "stop": None if tasks else "no resolved actionable direction; no speculative child"}


def prior_hint(task: ProposalTask, parent: dict[str, Any] | None, donor: dict[str, Any] | None = None) -> dict[str, Any]:
    """Project a full research row into prior-only specification fields."""
    hint = task.model_dump()
    if parent is not None:
        s = parent["structure"]
        hint["parent_specification"] = {k: s[k] for k in
            ("id", "family", "form", "mechanism", "labels", "operational", "coverage", "assertions", "primary_horizon")}
    if donor is not None and task.operator == "interaction":
        hint["donor_specification"] = {k: donor["structure"][k] for k in
            ("id", "family", "form", "mechanism", "operational", "coverage", "primary_horizon")}
    return hint


def observation_laws(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Falsifications stay distinct from insufficient evidence and never route trades."""
    laws = []
    for row in rows:
        if row["blades"]["placebo"]["state"] != "pass":
            continue
        spec = row["structure"]
        frozen = {a["id"]: a for a in spec["assertions"]}
        for outcome in row["blades"]["assertions"]:
            assertion = frozen[outcome["id"]]
            state = outcome["state"]
            if state not in ("hold", "violated", "untested"):
                raise ValueError("Unknown assertion verdict")
            kind = "传导层" if outcome["kind"] == "peak" else "条件层"
            laws.append({
                "id": "L-" + digest({"structure": row["id"], "assertion": outcome["id"]})[:16],
                "kind": kind, "claim": assertion["attribution"],
                "status": {"hold": "supported_in_A", "violated": "falsified_in_A",
                           "untested": "unresolved"}[state],
                "scope_predicate": spec["coverage"], "scope_negative": None,
                "confirmed": False, "evidence": [row["id"] + "." + outcome["id"]],
                "reopen": "freeze a new hypothesis before independent confirmation" if state != "untested"
                          else "increase independent date blocks until the preregistered effect is distinguishable",
                "model_terms": [],
            })
    return laws


def merge_induction(edits: dict[str, Any], laws: list[dict[str, Any]],
                    map_cells: list[dict[str, Any]]) -> dict[str, Any]:
    """Induction may suggest probes; it cannot rewrite frozen labels or declare PASS."""
    if set(edits) != {"probes", "connections"}:
        raise ValueError("Inducer may only suggest probes and evidence connections")
    allowed_cells = {c["id"] for c in map_cells if c["status"] == "unexplored"}
    law_ids = {law["id"] for law in laws}
    if len(edits["probes"]) > 3 or len(edits["connections"]) > 5:
        raise ValueError("Induction edit budget exceeded")
    probes = []
    for p in edits["probes"]:
        if set(p) != {"coordinate", "evidence"} or p["coordinate"] not in allowed_cells:
            raise ValueError("Invalid induction coordinate")
        if not p["evidence"] or not set(p["evidence"]) <= law_ids:
            raise ValueError("Induction probe needs existing law evidence")
        family, form = p["coordinate"].split("-F")
        probes.append(ProposalTask(family=family, form=int(form), operator="probe").model_dump())
    for connection in edits["connections"]:
        if set(connection) != {"laws", "hypothesis"} or len(connection["laws"]) < 2:
            raise ValueError("Connection needs two law references")
        if not set(connection["laws"]) <= law_ids or not isinstance(connection["hypothesis"], str):
            raise ValueError("Unknown law reference")
    return {"tasks": probes, "connections": edits["connections"],
            "vocabulary_edits": [], "frozen_labels_changed": False, "confirmed": False}
