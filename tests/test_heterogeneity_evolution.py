import json
from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
from engine.config import ResearchConfig
from engine.catalog import seed_structure
from engine.evolution import directional_profile, direction_report, evolved_specification, rule_expression
from engine.cycle import followup_tasks, ProposalTask, prior_hint
from engine.dsl import evaluate
from engine.continuation import prioritize_queue


def fixture_row():
    spec = seed_structure(0, "heterogeneity").model_dump()
    return {"id": spec["id"], "family": spec["family"], "form": spec["form"], "structure": spec,
        "verdict": "FAIL", "power": {"main_mde": 1.}, "measurement": {"coverage": .5},
        "blades": {"placebo": {"state": "fail"}, "assertions": [{"kind":"sign","state":"violated"}]},
        "discovery": {"forest": {"training_rules": [{"gates": [
            {"field":"market_cap_pct","cut_id":"cap","branch":"low"},
            {"field":"amihud_pct","cut_id":"illiquid","branch":"high"}], "orientation":-1}]}}}


def test_heterogeneity_beats_failed_aggregate_and_children_have_frozen_lineage():
    parent=fixture_row()
    donor=deepcopy(parent);donor["id"]="S-donor-1";donor["structure"]["id"]=donor["id"]
    donor["family"]="M1";donor["structure"]["family"]="M1"
    tasks=followup_tasks(parent,[parent,donor])["tasks"]
    assert [t["operator"] for t in tasks]==["condition","interaction"]
    child=ProposalTask.model_validate(tasks[0])
    assert child.orientation==-1 and len(child.gates)==2
    hint=prior_hint(ProposalTask.model_validate(tasks[1]),parent,donor)
    assert hint["donor_specification"]["id"]==donor["id"]
    assert "measurement" not in str(hint) and "training_effect" not in str(hint)
    queue=[t.model_dump() for t in __import__("engine.cycle",fromlist=["initial_tasks"]).initial_tasks()]
    queue.extend(tasks)
    prioritize_queue(queue,2,5)
    assert queue[0]["operator"]=="condition"


def test_direction_is_frozen_before_later_sign_flip():
    rng=np.random.default_rng(4)
    first=pd.Series(-.03+rng.normal(0,.005,1000))
    config=ResearchConfig(mode="fast",n_boot=100)
    a=directional_profile(first,5,config)
    changed=first.copy();changed.iloc[600:]=10
    b=directional_profile(changed,5,config)
    assert a["reverse_candidate"] and b["reverse_candidate"]
    assert a["training"]==b["training"] and a["direction"]==b["direction"]==-1
    assert b["validation"]["mean"]>a["validation"]["mean"]


def test_condition_boundaries_and_composition_preserve_missing_coverage():
    x=pd.DataFrame([[20.,50.,80.,np.nan]])
    fields={"x":x,"y":x.iloc[:,::-1].set_axis(x.columns,axis=1),
            "market_cap_pct":x,"amihud_pct":100-x,"in_pool":x.notna()}
    cuts={"cap":{"field":"market_cap_pct","value":50.},
          "illiquid":{"field":"amihud_pct","value":50.}}
    parent={"id":"p","operational":["xs_z(x)","xs_rank(x)","x"],"coverage":"in_pool","primary_horizon":5}
    hint={"operator":"condition","parent_specification":parent,"orientation":-1,
          "gates":[{"field":"market_cap_pct","cut_id":"cap","branch":"low"},
                   {"field":"amihud_pct","cut_id":"illiquid","branch":"high"}]}
    child=evolved_specification(hint,cuts)
    mask=evaluate(child["coverage"],fields,cuts)
    assert mask.iloc[0].tolist()==[True,False,False,False]
    signal=evaluate(child["operational"][0],fields,cuts)
    np.testing.assert_allclose(signal,-evaluate(parent["operational"][0],fields,cuts),equal_nan=True)
    donor={**parent,"id":"d","operational":["xs_z(y)","xs_rank(y)","y"]}
    product=evolved_specification({"operator":"interaction","parent_specification":parent,"donor_specification":donor},cuts)
    np.testing.assert_allclose(evaluate(product["operational"][0],fields,cuts),
        evaluate("mul(xs_z(xs_z(x)), xs_z(xs_z(y)))",fields,cuts),equal_nan=True)


def test_reverse_costs_are_recomputed_not_negated():
    from engine.data import MarketPanel
    n=400
    signal=pd.DataFrame(np.tile(np.arange(40),(n,1)),index=pd.bdate_range("2017-01-01",periods=n))
    raw=(20-signal)*.001
    labels={"raw_5":raw,"net_5":raw-.003}
    panel=MarketPanel({"close":signal,"in_pool":signal.notna()},labels,[])
    spec=seed_structure(0,"reverse")
    stored={"signal_0":signal,"ic_e1_h5":pd.DataFrame({"ic":np.full(n,-.8)},index=signal.index)}
    report=direction_report(stored,panel,spec,ResearchConfig(mode="fast",n_boot=100))
    forward=report["costed_orientations"]["forward"]["training"]["mean"]
    reverse=report["costed_orientations"]["reverse"]["training"]["mean"]
    assert reverse>0 and reverse!=pytest.approx(-forward)
    assert report["reverse_candidate"] and not report["formal"]


def test_signed_placebo_has_equal_tail_probability():
    from engine.placebo import full_market_placebo
    rng=np.random.default_rng(5);x=pd.DataFrame(rng.normal(size=(180,40)))
    cfg=ResearchConfig(mode="fast",n_placebo=19,workers=1)
    positive=full_market_placebo(x,x,cfg)
    negative=full_market_placebo(-x,x,cfg)
    assert positive["tests"][0]["p"]==negative["tests"][0]["p"]
    assert negative["tests"][0]["observed"]<0


def test_real_forest_exports_opposing_joint_conditions_with_zero_aggregate():
    from engine.discovery import forest_propose
    from threadpoolctl import threadpool_limits
    rng=np.random.default_rng(34);days=1000;stocks=120;size=days*stocks
    a=rng.choice([-1.,1.],size);b=rng.choice([-1.,1.],size)
    f=rng.normal(size=size);r=.8*f*a*b+rng.normal(0,.15,size)
    frame=pd.DataFrame({"date":np.repeat(pd.bdate_range("2016-01-01",periods=days),stocks),
        "symbol":np.tile(np.arange(stocks),days),"f":f,"r":r,"a":a,"b":b,
        "log_cap":rng.normal(size=size),"volatility":rng.normal(size=size),
        "log_turnover":rng.normal(size=size),"industry":np.tile(["A","B"],size//2)})
    cuts={"a0":{"field":"a","value":0.},"b0":{"field":"b","value":0.}}
    with threadpool_limits(limits=1):
        result=forest_propose(frame,["a","b"],cuts,ResearchConfig(mode="fast",n_trees=10,n_boot=100,workers=1))
    assert abs(np.dot(f,r)/np.dot(f,f))<.02
    assert result["training_rules"]
    assert {r["orientation"] for r in result["training_rules"]}=={-1,1}
    assert any(len({g["field"] for g in r["gates"]})==2 for r in result["training_rules"])
    assert all(not r["independent_confirmation"] for r in result["training_rules"])


def test_model_review_receives_exact_evolved_signal_before_freeze(monkeypatch):
    from engine.llm import DeepSeek
    from engine.catalog import build_map
    from engine.forms import OperationalPlan
    parent=fixture_row()
    task=ProposalTask.model_validate(followup_tasks(parent,[parent])["tasks"][0])
    hint=prior_hint(task,parent)
    cuts={"cap":{"field":"market_cap_pct","value":50.,"side":"low"},
          "illiquid":{"field":"amihud_pct","value":50.,"side":"high"}}
    plan=OperationalPlan(base_field="ret_5d",direction=-1,moderator="market_cap_pct",cut_id="cap").model_dump()
    reviewed=[]
    def request(role,context,instruction,nonce=""):
        if role=="proposer" and "form_contract" in context.get("constraints",{}):
            return {"name":"条件化反向机制","mechanism":"在冻结市值与流动性条件内检验父机制的反向预测，而非宣称已成功。","peak_range":[1,5],"plan":plan}
        if role=="operationalizer":
            return plan
        if role=="proposer":
            return {"side_predictions":[{"moderator":"market_cap_pct","direction":1,"rationale":"条件机制假设"},
                {"moderator":"amihud_pct","direction":-1,"rationale":"流动性机制假设"}]}
        if role=="reviewer":
            reviewed.append(context["operational"])
            return {"approved":True,"reason":"controlled logic review"}
        raise AssertionError(role)
    client=DeepSeek.__new__(DeepSeek);monkeypatch.setattr(client,"request",request)
    cell=next(c for c in build_map() if c["family"]==task.family and c["form"]==task.form)
    child=client.propose(cell,"reviewed",0,{"ret_5d","market_cap_pct","amihud_pct","in_pool","industry"},cuts,hint)
    expected=evolved_specification(hint,cuts)
    assert reviewed[0]["operational"]==child.operational==expected["operational"]
    assert reviewed[0]["coverage"]==child.coverage==expected["coverage"]
    assert child.lineage["depth"]==1 and child.lineage["parent"]==parent["id"]
    assert child.lineage["origin"]=="training_informed"
    assert child.lineage["frozen_evolved_signal"]==expected


def test_validation_outcomes_never_choose_training_rules(monkeypatch):
    from engine import discovery
    train=pd.DataFrame({"date":pd.bdate_range("2016-01-01",periods=800)})
    validation=pd.DataFrame({"date":pd.bdate_range("2020-01-01",periods=400),"r":1.})
    frozen={"gates":[{"field":"market_cap_pct","cut_id":"cap","branch":"low"}],"orientation":-1}
    monkeypatch.setattr(discovery,"forest_propose",lambda *args: {
        "candidates":[{"name":"market_cap_pct","frequency":1.}],"training_rules":[frozen]})
    monkeypatch.setattr(discovery,"blade_icm",lambda frame,*args: {"p":.001 if frame.r.mean()>0 else 1.})
    cuts={"cap":{"field":"market_cap_pct","value":50.}}
    a=discovery.evaluate_split(train,validation,["market_cap_pct"],cuts,ResearchConfig(),5,0)
    validation.r=-1.
    b=discovery.evaluate_split(train,validation,["market_cap_pct"],cuts,ResearchConfig(),5,0)
    assert a["p"]!=b["p"] and a["training_rules"]==b["training_rules"]==[frozen]


def test_rule_budget_preserves_both_effect_directions():
    parent=fixture_row()
    rule=parent["discovery"]["forest"]["training_rules"][0]
    first=deepcopy(rule);first["orientation"]=1
    second=deepcopy(first);second["gates"][0]["branch"]="high"
    negative=deepcopy(rule)
    parent["discovery"]["forest"]["training_rules"]=[first,second,negative]
    tasks=followup_tasks(parent,[parent])["tasks"]
    assert {t["orientation"] for t in tasks if t["operator"]=="condition"}=={-1,1}
