"""Training-only evolution evidence and executable, bounded signal composition.

Absolute effects are diagnostics, never abs(return) profits. Every selected direction
and gate is a new exploratory hypothesis requiring independent confirmation.
"""
import numpy as np
import pandas as pd
from engine.metrics import summarize, group_returns
from engine.dsl import evaluate


def training_stop(length, horizon):
    return max(0, min(800, int(length * .55)) - max(15, horizon + 1))


def directional_profile(series, horizon, config):
    stop = training_stop(len(series), horizon)
    training = summarize(series.iloc[:stop], horizon, config)
    validation = summarize(series.iloc[stop + max(15, horizon + 1):], horizon, config)
    mean = training.get("mean")
    direction = -1 if mean is not None and mean < 0 else 1
    p = min(1., 2 * min(training.get("p", 1.), training.get("p_negative", 1.)))
    return {"training": training, "validation": validation,
            "absolute_training_effect": abs(mean) if mean is not None else None,
            "direction": direction, "two_sided_training_p": p,
            "reverse_candidate": direction == -1 and p < .05,
            "selection_segment": "A_training_prefix", "training_rows": stop,
            "independent_confirmation": False}


def direction_report(stored, panel, structure, config):
    h = structure.primary_horizon
    ic = directional_profile(stored[f"ic_e1_h{h}"].ic, h, config)
    signal = stored["signal_0"]
    raw = panel.labels.get(f"raw_{h}")
    if raw is None:
        return {"ic": ic, "formal": False}
    forward = group_returns(signal, raw)
    spread = directional_profile(forward.Q5 - forward.Q1, h, config)
    stop = spread["training_rows"]
    orientations = {}
    for name, sign in (("forward", 1), ("reverse", -1)):
        net = group_returns(sign * signal, panel.labels[f"net_{h}"])
        excess = net.Q5 - raw.mean(axis=1)
        orientations[name] = {"training": summarize(excess.iloc[:stop], h, config),
            "validation": summarize(excess.iloc[stop + max(15, h + 1):], h, config)}
    return {"ic": ic, "raw_spread": spread, "costed_orientations": orientations,
            "formal": False, "interpretation": "Reranked long baskets with fixed costs; not a tradable backtest",
            "reverse_candidate": (ic["reverse_candidate"] and ic["two_sided_training_p"] < .025) or (spread["reverse_candidate"] and spread["two_sided_training_p"] < .025)}


def rule_expression(rule, cuts):
    terms = []
    for gate in rule["gates"]:
        row = cuts[gate["cut_id"]]
        if row["field"] != gate["field"]:
            raise ValueError("Condition field differs from its frozen cut")
        op = "<" if gate["branch"] == "low" else ">="
        terms.append(f'({gate["field"]} {op} {float(row["value"])!r})')
    if not 1 <= len(terms) <= 4:
        raise ValueError("Condition must contain one to four frozen gates")
    return " and ".join(terms)


def evolved_specification(hint, cuts):
    """Compose specifications before model review and measurement, never edit results."""
    operator = hint.get("operator")
    if operator not in {"condition", "reverse", "interaction"}:
        return None
    parent = hint.get("parent_specification")
    if not parent:
        raise ValueError("Evolution requires a frozen parent specification")
    expressions = list(parent["operational"])
    coverage = parent["coverage"]
    if operator == "condition":
        coverage = f"({coverage}) and ({rule_expression(hint, cuts)})"
    elif operator == "interaction":
        donor = hint.get("donor_specification")
        if not donor or donor["id"] == parent["id"]:
            raise ValueError("Interaction requires a distinct frozen donor")
        expressions = [f"mul(xs_z({a}), xs_z({b}))"
                       for a, b in zip(expressions, donor["operational"])]
        coverage = f"({coverage}) and ({donor['coverage']})"
    if hint.get("orientation", 1) == -1:
        expressions = [f"neg({expr})" for expr in expressions]
    return {"operational": expressions, "coverage": coverage,
            "primary_horizon": parent["primary_horizon"]}


def research_role(row):
    forest = row.get("discovery", {}).get("forest", {})
    rules = forest.get("training_rules", [])
    reverse = row.get("directionality", {}).get("reverse_candidate", False)
    return {"role": "heterogeneity_component" if rules else "reverse_component" if reverse else "unresolved_component",
            "training_rules": len(rules), "reverse_candidate": reverse,
            "single_cell_alpha_required": False, "formal": False}


def evolution_summary(rows):
    children = [r for r in rows if r["structure"]["lineage"].get("parent")]
    return {"objective": "heterogeneity_and_evolution", "components": len(rows),
            "conditional_rules": sum(len(r.get("discovery", {}).get("forest", {}).get("training_rules", [])) for r in rows),
            "reverse_candidates": sum(bool(r.get("directionality", {}).get("reverse_candidate")) for r in rows),
            "children_measured": len(children),
            "child_comparisons": sum("evolution_validation" in r for r in children),
            "independent_confirmed": 0}


def compare_child(stored, panel, structure, history, config, cuts):
    """Common-date, common-coverage child/parent/donor diagnostics; A reuse is explicit."""
    lineage = structure.lineage
    parent = next((r for r in history if r["id"] == lineage.get("parent")), None)
    if parent is None:
        return None
    h = structure.primary_horizon
    child = stored["signal_0"]
    label = panel.labels.get(f"industry_resid_{h}")
    if label is None:
        return {"state": "untested", "reason": "comparison labels absent", "formal": False}
    from engine.metrics import daily_ic
    signals = {"child": child}
    for name, reference in (("parent", parent),
        ("donor", next((r for r in history if r["id"] == lineage.get("donor")), None))):
        if reference:
            spec = reference["structure"]
            mask = evaluate(spec["coverage"], panel.fields, cuts).fillna(False).astype(bool)
            signals[name] = evaluate(spec["operational"][0], panel.fields, cuts).where(mask)
    common = label.notna()
    for signal in signals.values():
        common &= signal.notna()
    stop = training_stop(len(child), h) + max(15, h + 1)
    sequences = {name: daily_ic(signal.where(common), label.where(common)).iloc[stop:]
                 for name, signal in signals.items()}
    differences = {name: summarize(sequences["child"] - seq, h, config)
                   for name, seq in sequences.items() if name != "child"}
    parent_signal = signals["parent"]
    outside = parent_signal.where(child.isna())
    outside_ic = daily_ic(outside, label).iloc[stop:]
    scope_contrast = summarize(sequences["parent"] - outside_ic, h, config)
    return {"state": "descriptive_A_reuse", "comparisons": differences,
            "parent_inside_minus_outside_scope": scope_contrast,
            "common_observations": int(common.iloc[stop:].sum().sum()),
            "formal": False, "independent_confirmation": False,
            "interpretation": "Parent and donor ablations on identical coverage; reused A dates cannot establish child superiority"}
