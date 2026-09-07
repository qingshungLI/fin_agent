
import numpy as np
import pandas as pd
import pytest

from engine.catalog import seed_structure
from engine.cycle import ProposalTask, followup_tasks, initial_tasks, merge_induction, prior_hint
from engine.dsl import evaluate
from engine.forms import OperationalPlan, compile_form


@pytest.fixture
def inputs():
    rng = np.random.default_rng(38)
    dates, symbols = pd.bdate_range("2020-01-01", periods=100), [f"S{i}" for i in range(40)]
    x = pd.DataFrame(rng.normal(size=(100, 40)), index=dates, columns=symbols)
    fields = {"ret_1d": x, "ret_5d": x.rolling(5).mean(),
              "turnover_today": x.abs() + 1,
              "industry": pd.DataFrame(np.tile(["A"]*20+["B"]*20, (100, 1)), index=dates, columns=symbols),
              "in_pool": x.notna(), "not_suspended": x.notna(),
              "market_cap_pct": x.rank(axis=1, pct=True)*100,
              "failed_limit_up": x > 1}
    cuts = {"cap_low": {"field": "market_cap_pct", "side": "low", "value": 30.}}
    return fields, cuts


@pytest.mark.parametrize("form", range(1, 8))
def test_every_form_is_executable_and_history_invariant(inputs, form):
    fields, cuts = inputs
    extra = {5: {"pair_field": "turnover_today"},
             6: {"moderator": "market_cap_pct", "cut_id": "cap_low"},
             7: {"event": "return_shock"}}.get(form, {})
    result = compile_form(form, OperationalPlan(base_field="ret_1d", direction=-1, **extra),
                          set(fields), cuts, "M2")
    for expr in [*result["operational"], result["coverage"]]:
        full = evaluate(expr, fields, cuts)
        shorter = evaluate(expr, {k:v.iloc[:80] for k,v in fields.items()}, cuts)
        assert np.allclose(full.iloc[:80], shorter, equal_nan=True)
    if form in (6, 7):
        mask = evaluate(result["coverage"], fields, cuts).fillna(False).astype(bool)
        signal = evaluate(result["operational"][0], fields, cuts).where(mask)
        assert signal.where(~mask).isna().all().all()
        assert not mask.all().all()
    if form == 4:
        assert all("industry_mean" in expr for expr in result["operational"])
    if form == 5:
        assert all("turnover_today" in expr and "ret_1d" in expr for expr in result["operational"])


def test_invalid_form_contracts_are_rejected(inputs):
    fields, cuts = inputs
    with pytest.raises(ValueError, match="two distinct"):
        compile_form(5, OperationalPlan(base_field="ret_1d", pair_field="ret_1d", direction=1), set(fields), cuts, "M2")
    with pytest.raises(ValueError, match="frozen cut"):
        compile_form(6, OperationalPlan(base_field="ret_1d", moderator="market_cap_pct", cut_id="invented", direction=1), set(fields), cuts, "M2")
    with pytest.raises(ValueError, match="unavailable"):
        compile_form(7, OperationalPlan(base_field="ret_1d", event="return_shock", direction=1), set(fields), cuts, "M5")


def research_row():
    s = seed_structure(0, "cycle").model_dump()
    return {"id": s["id"], "family": s["family"], "form": s["form"], "structure": s,
            "power": {"main_mde": .01}, "measurement": {"coverage": .8},
            "blades": {"placebo": {"state": "pass"}, "assertions": [
                {"id": a["id"], "kind": a["kind"], "state": "untested"} for a in s["assertions"]]},
            "discovery": {}}


def test_queue_does_not_turn_uncertainty_or_artifacts_into_new_mechanisms():
    row = research_row()
    assert followup_tasks(row, [row])["tasks"] == []
    row["blades"]["assertions"][-1]["state"] = "violated"
    assert followup_tasks(row, [row])["tasks"][0]["operator"] == "cross_family"
    row["blades"]["placebo"]["state"] = "fail"
    assert followup_tasks(row, [row])["tasks"] == []


def test_forest_children_only_receive_variable_name_and_prior():
    row = research_row()
    row["discovery"] = {"forest": {"p_median": .001, "selection_frequency": {"market_cap_pct": .9}}}
    task = ProposalTask.model_validate(followup_tasks(row, [row])["tasks"][0])
    hint = prior_hint(task, row)
    assert hint["moderator"] == "market_cap_pct"
    assert not any(key in str(hint) for key in ("p_median", "selection_frequency", "main_mde", "measurement"))
    row["discovery"]["forest"]["p_median"] = .8
    assert followup_tasks(row, [row])["tasks"] == []


def test_frozen_depth_and_initial_form_coverage():
    tasks = initial_tasks()
    assert [(t.family, t.form) for t in tasks[:4]] == [("M2",3),("M2",1),("M1",3),("M1",1)]
    assert {t.form for t in tasks[:9]} == set(range(1,8))
    assert len({t.key for t in tasks}) == len(tasks)
    row = research_row()
    row["structure"]["lineage"]["depth"] = 2
    row["blades"]["assertions"][-1]["state"] = "violated"
    assert followup_tasks(row, [row])["tasks"] == []


def test_inducer_cannot_promote_or_mutate_evidence():
    from engine.catalog import build_map
    with pytest.raises(ValueError):
        merge_induction({"probes": [], "connections": [], "confirmed": True}, [], build_map())
    with pytest.raises(ValueError, match="evidence"):
        merge_induction({"probes": [{"coordinate": "M1-F1", "evidence": ["unknown"]}],
                         "connections": []}, [], build_map())

def test_batch_controls_false_mechanisms_with_real_main_effects():
    from engine.confirmation import batch_decisions
    rows = [{"id": str(i), "p": 1e-8,
             "assertions": [{"state": "hold", "p_support": .02}]} for i in range(8)]
    assert all(r["verdict"] == "UNDECIDABLE" and r["adjusted_p"] == pytest.approx(.16)
               for r in batch_decisions(rows))
    rows[0]["assertions"] = [{"state": "hold"}]
    assert batch_decisions(rows)[0]["formal"] is False

def test_conditional_side_test_uses_ungated_parent():
    from engine.blades import blade_assertion
    from engine.catalog import seed_structure, Assertion
    from engine.config import ResearchConfig
    from engine.data import MarketPanel
    rng=np.random.default_rng(149)
    dates=pd.bdate_range("2010-01-01",periods=500)
    x=pd.DataFrame(rng.normal(size=(500,120)),index=dates)
    z=pd.DataFrame(np.tile([20.]*60+[80.]*60,(500,1)),index=dates)
    returns=x.where(z>50,-x)+rng.normal(scale=.5,size=x.shape)
    s=seed_structure(0,"condition")
    s=s.model_copy(update={"assertions":[Assertion(id="P4",kind="side",subject="market_cap_pct",
        relation="difference",direction=1,attribution="fixed synthetic contrast")],
        "lineage":{"moderator":"market_cap_pct"}})
    panel=MarketPanel({"market_cap_pct":z},{"industry_resid_5":returns},[],{})
    stored={"signal_0":x.where(z>50),"ungated_signal":x,
            "condition_cut":pd.DataFrame({"value":[50.]})}
    result=blade_assertion(s,panel,stored,ResearchConfig())
    assert result[0]["state"]=="hold"
    stored.pop("ungated_signal")
    assert blade_assertion(s,panel,stored,ResearchConfig())[0]["state"]=="untested"


def test_rolling_z_is_stable_after_large_past_outlier_and_tiny_units():
    from engine.dsl import evaluate
    rng=np.random.default_rng(2)
    values=np.r_[1e-3, rng.uniform(4e-11,4.6e-11,299)]
    x=pd.DataFrame({"A":values,"constant":np.ones(300)*1e-12})
    out=evaluate("ts_z(amihud, 20)",{"amihud":x})
    scaled=evaluate("ts_z(amihud, 20)",{"amihud":x*.1})
    np.testing.assert_allclose(out,scaled,rtol=1e-10,atol=1e-10,equal_nan=True)
    expected=np.array([(values[i]-values[i-19:i+1].mean())/values[i-19:i+1].std(ddof=1)
                       for i in range(19,len(values))])
    np.testing.assert_allclose(out.A.iloc[19:],expected,atol=1e-10)
    assert out.constant.isna().all()
    shorter=evaluate("ts_z(amihud, 20)",{"amihud":x.iloc[:200]})
    np.testing.assert_allclose(out.iloc[:200],shorter,equal_nan=True)


def test_rejected_priors_consume_budget_once_and_resume_without_remeasurement(tmp_path, monkeypatch):
    from engine import pipeline
    from engine.config import ResearchConfig
    from engine.data import MarketPanel
    root=tmp_path/"project"
    (root/"engine").mkdir(parents=True)
    data=root/"data";data.mkdir()
    panel=MarketPanel({"close":pd.DataFrame({"S":[1.,2.]},index=pd.bdate_range("2020-01-01",periods=2))},{},[],{})
    calls=[]
    class RejectingModel:
        def configuration_identity(self): return {"model": "initial-test-model"}
        def __init__(self,*args,**kwargs): pass
        def propose(self,*args,**kwargs):
            calls.append(1)
            raise ValueError("synthetic invalid prior")
    monkeypatch.setattr(pipeline,"ROOT",root)
    monkeypatch.setattr(pipeline,"DeepSeek",RejectingModel)
    monkeypatch.setattr(pipeline,"cached_panel",lambda *args,**kwargs:(panel,False))
    monkeypatch.setattr(pipeline,"freeze_cuts",lambda *args,**kwargs:{})
    def forbidden(*args,**kwargs):
        raise AssertionError("Rejected priors must never reach measurement")
    monkeypatch.setattr(pipeline,"measure_panel",forbidden)
    config=ResearchConfig(provider="llm",max_structures=3)
    result=pipeline.run_research(config,"rejected",data,root/"artifacts")
    assert result["status"]=="COMPLETED" and result["completed"]==[]
    assert result["attempts"]==3 and len(result["rejected_priors"])==3
    assert len(calls)==3
    resumed=pipeline.run_research(config,"rejected",data,root/"artifacts")
    assert resumed==result and len(calls)==3

    monkeypatch.setattr(RejectingModel,"configuration_identity",lambda self:{"model":"changed-test-model"})
    with pytest.raises(ValueError,match="Resume requires unchanged"):
        pipeline.run_research(config,"rejected",data,root/"artifacts")
    assert len(calls)==3
