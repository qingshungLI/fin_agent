import json

import httpx
import numpy as np
import pandas as pd
import pytest

from engine.audit import write_json
from engine.blades import blade_placebo, iaaft
from engine.config import ResearchConfig
from engine.confirmation import batch_decisions
from engine.llm import DeepSeek, role_context
from engine.pipeline import json_safe, project_lock
from engine.portfolio import position_path


def test_role_firewall_rejects_effect_and_holdout():
    for name in ["ic", "returns", "B", "posterior"]:
        with pytest.raises(ValueError, match="firewall"):
            role_context("proposer", **{name: .5})
    with pytest.raises(ValueError):
        role_context("bettor", coordinate="M2")
    assert role_context("bettor", labels={}, assertions=[]) == {"labels": {}, "assertions": []}


def test_llm_retries_and_never_persists_secret(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("API_KEY=test-secret\n")
    requests = []
    def post(client, url, **kwargs):
        requests.append(kwargs)
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}],
            "usage": {"total_tokens": 10}})
    monkeypatch.setattr(httpx.Client, "post", post)
    client = DeepSeek(tmp_path / "cache", env)
    for _ in range(2):
        assert client.request("bettor", {"labels": {}, "assertions": []}, "JSON") == {"ok": True}
    assert len(requests) == 1
    assert "test-secret" not in next((tmp_path / "cache").glob("*.json")).read_text()


def test_batch_holm_and_necessary_conditions():
    rows = [
        {"id": "A", "p": .001, "assertions": [{"state": "hold", "p_support": .001}]},
        {"id": "B", "p": .001, "assertions": [{"state": "violated"}]},
        {"id": "C", "p": .001, "assertions": [{"state": "untested"}]},
        {"id": "D", "p": .9, "assertions": [{"state": "hold", "p_support": .001}]},
    ]
    decisions = batch_decisions(rows)
    assert [r["verdict"] for r in decisions] == ["PASS", "FAIL", "UNDECIDABLE", "UNDECIDABLE"]
    assert decisions[0]["adjusted_p"] == pytest.approx(.004)


def test_project_single_writer(tmp_path):
    with project_lock(tmp_path), pytest.raises(RuntimeError, match="writer"), project_lock(tmp_path):
        pass


def test_sparse_outputs_are_json_safe(tmp_path):
    write_json(tmp_path / "x.json", json_safe({"x": np.nan, "y": np.float64(1)}))
    assert json.loads((tmp_path / "x.json").read_text()) == {"x": None, "y": 1.0}


def test_iaaft_preserves_marginals_and_is_deterministic():
    x = np.random.default_rng(2).normal(size=(128, 8))
    a, error = iaaft(x, np.random.default_rng(4))
    b, _ = iaaft(x, np.random.default_rng(4))
    assert np.array_equal(a, b)
    assert np.array_equal(np.sort(a, axis=0), np.sort(x, axis=0))
    assert error < .1


def test_fast_permutation_resolution_is_not_a_failure():
    c = ResearchConfig(mode="engineering", n_placebo=99)
    x = pd.DataFrame(np.random.default_rng(1).normal(size=(200, 40)))
    result = blade_placebo(x, x, c)
    assert result["state"] == "untested"


def test_position_path_preserves_outside_coverage():
    weights = pd.DataFrame({"A": [np.nan, 1., np.nan, np.nan], "B": [np.nan]*4})
    result = position_path(weights, 1)
    assert result.B.isna().all()
    assert result.A.iloc[1] == 1

def test_placebo_worker_count_does_not_change_results():
    rng = np.random.default_rng(123)
    x = pd.DataFrame(rng.normal(size=(180, 35)))
    y = pd.DataFrame(.1 * x.to_numpy() + rng.normal(size=x.shape))
    config = ResearchConfig(mode="engineering", n_placebo=100, workers=1)
    one = blade_placebo(x, y, config)
    many = blade_placebo(x, y, config.model_copy(update={"workers": 2}))
    assert one == many


def test_block_summary_uses_finite_block_uncertainty():
    from engine.metrics import summarize
    x = pd.Series(np.random.default_rng(7).normal(size=400))
    result = summarize(x, 5, ResearchConfig())
    assert result["inference_blocks"] == 20
    assert result["se"] >= result["bootstrap_se"]
    assert 0 < result["p"] < 1


def test_convergent_expressions_cannot_reverse_one_signal():
    from engine.catalog import check_convergent_orientation, seed_structure
    x = pd.DataFrame(np.random.default_rng(7).normal(size=(100, 40)))
    structure = seed_structure(0, "test")
    structure = structure.model_copy(update={"operational": [
        "xs_z(ret_5d)", "neg(xs_z(ret_5d))", "xs_rank(ret_5d)"]})
    with pytest.raises(ValueError, match="contradictory orientations"):
        check_convergent_orientation(structure, {"ret_5d": x}, {})


def test_blind_bets_do_not_receive_default_probabilities(tmp_path, monkeypatch):
    from engine.catalog import seed_structure
    env = tmp_path / ".env"
    env.write_text("API_KEY=test-only\n")
    client = DeepSeek(tmp_path / "cache", env)
    def request(role, context, instruction, nonce=""):
        assert role == "bettor"
        assert all("prior_p" not in a and "weight" not in a for a in context["assertions"])
        return {"probabilities": {a["id"]: .51 for a in context["assertions"]}}
    monkeypatch.setattr(client, "request", request)
    assert all(value["probability"] == .51 for value in client.bets(seed_structure(0, "test")).values())


def test_resume_rejects_tampered_frozen_cut_before_loading_market_data(tmp_path, monkeypatch):
    from engine import pipeline
    from engine.cache import file_hash
    root = tmp_path / "project"
    (root / "engine").mkdir(parents=True)
    data = root / "data"
    data.mkdir()
    folder = root / "artifacts" / "resume-test"
    folder.mkdir(parents=True)
    cut = folder / "cuts.json"
    write_json(cut, {"fixed": 50})
    config = ResearchConfig()
    write_json(folder / "checkpoint.json", {
        "status": "COMPLETED", "run_id": "resume-test", "completed": [],
        "identity": {"config": config.model_dump(), "data_root": str(data.resolve()),
                     "discovery": False, "bayes": False, "code": {}, "sources": {}},
        "artifact_hashes": {"cuts.json": file_hash(cut)}})
    write_json(cut, {"fixed": 70})
    monkeypatch.setattr(pipeline, "ROOT", root)
    def forbidden(*args, **kwargs):
        raise AssertionError("Market data must remain unread")
    monkeypatch.setattr(pipeline, "cached_panel", forbidden)
    with pytest.raises(ValueError, match="Checkpoint artifact was modified"):
        pipeline.run_research(config, "resume-test", data, root / "artifacts")


@pytest.mark.parametrize("rank", [False, True])
def test_daily_ic_against_independent_scipy_with_gaps_ties_and_constants(rank):
    from scipy.stats import pearsonr, rankdata

    from engine.metrics import daily_ic
    rng = np.random.default_rng(931)
    x = np.round(rng.normal(size=(260, 73)), 1)
    y = np.round(rng.normal(size=x.shape), 1)
    x[rng.random(x.shape) < .1] = np.nan
    y[rng.random(y.shape) < .1] = np.nan
    x[0] = np.nan
    x[1] = 2.
    y[2] = 4.
    x[3, 29:] = np.nan
    expected = []
    for left, right in zip(x, y):
        valid = np.isfinite(left) & np.isfinite(right)
        a, b = left[valid], right[valid]
        if len(a) < 30 or np.ptp(a) == 0 or np.ptp(b) == 0:
            expected.append(np.nan)
            continue
        if rank:
            a, b = rankdata(a), rankdata(b)
        expected.append(pearsonr(a,b).statistic)
    actual = daily_ic(pd.DataFrame(x), pd.DataFrame(y), rank=rank)
    np.testing.assert_allclose(actual, expected, atol=1e-12, rtol=0, equal_nan=True)
