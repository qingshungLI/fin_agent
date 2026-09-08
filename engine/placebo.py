"""Full-universe placebo tests conditional on the observed daily eligibility mask.

No security subsampling, complete-column filtering or missing-value imputation.
Temporal surrogates act within contiguous eligible spells, never across ST/gaps.
Short spells remain unchanged in the statistic rather than being dropped.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from time import perf_counter
from typing import Any
import numpy as np
import pandas as pd


def masked_ic(x, y, min_cross_section=2):
    valid = np.isfinite(x) & np.isfinite(y)
    counts = valid.sum(axis=1)
    a = np.where(valid, x, 0.)
    b = np.where(valid, y, 0.)
    mx = a.sum(axis=1) / np.maximum(counts, 1)
    my = b.sum(axis=1) / np.maximum(counts, 1)
    a = np.where(valid, a - mx[:, None], 0.)
    b = np.where(valid, b - my[:, None], 0.)
    denominator = np.sqrt(np.sum(a*a, axis=1)*np.sum(b*b, axis=1))
    good = (counts >= min_cross_section) & (denominator > 1e-15)
    if not good.any():
        return None
    return float(np.mean(np.sum(a*b, axis=1)[good]/denominator[good]))


@dataclass(frozen=True)
class Spell:
    positions: np.ndarray
    values: np.ndarray
    sorted_values: np.ndarray
    amplitude: np.ndarray


def spell_plan(x):
    """Group all contiguous finite spells by length for batched FFTs."""
    groups = {}
    rows, cols = x.shape
    for column in range(cols):
        valid = np.isfinite(x[:, column])
        changes = np.diff(np.r_[False, valid, False].astype(np.int8))
        for start, stop in zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)):
            groups.setdefault(int(stop-start), []).append((int(start), column))
    plan = []
    for length, spans in sorted(groups.items()):
        starts, columns = np.asarray(spans).T
        positions = (starts[None, :] + np.arange(length)[:, None])*cols + columns[None, :]
        values = x.ravel()[positions]
        plan.append(Spell(positions, values, np.sort(values, axis=0),
                          np.abs(np.fft.rfft(values, axis=0))))
    return plan


def temporal_surrogate(x, plan, rng, kind, horizon):
    out = np.full(x.size, np.nan)
    max_error = 0.
    for spell in plan:
        values = spell.values
        length, columns = values.shape
        if kind == "time_shift":
            if length <= 2*horizon+1:
                surrogate = values
            else:
                shifts = rng.integers(horizon+1, length-horizon, size=columns)
                order = (np.arange(length)[:, None] - shifts[None, :]) % length
                surrogate = np.take_along_axis(values, order, axis=0)
        elif length < 4:
            surrogate = values
        else:
            order = np.argsort(rng.random(values.shape), axis=0)
            surrogate = np.take_along_axis(values, order, axis=0)
            for _ in range(30):
                phase = np.angle(np.fft.rfft(surrogate, axis=0))
                filtered = np.fft.irfft(spell.amplitude*np.exp(1j*phase), n=length, axis=0)
                order = np.argsort(filtered, axis=0)
                surrogate = np.empty_like(filtered)
                np.put_along_axis(surrogate, order, spell.sorted_values, axis=0)
            error = np.linalg.norm(np.abs(np.fft.rfft(surrogate, axis=0))-spell.amplitude)
            scale = max(float(np.linalg.norm(spell.amplitude)), 1e-12)
            max_error = max(max_error, float(error/scale))
        out[spell.positions] = surrogate
    return out.reshape(x.shape), max_error


def within_day_surrogate(x, rng):
    finite = np.isfinite(x)
    # Invalid cells are sorted to the end, then the shuffled valid values are
    # scattered back to the original valid positions.
    order = np.argsort(np.where(finite, rng.random(x.shape), np.inf), axis=1)
    shuffled = np.take_along_axis(x, order, axis=1)
    rank = np.maximum(np.cumsum(finite, axis=1)-1, 0)
    return np.where(finite, np.take_along_axis(shuffled, rank, axis=1), np.nan)


def full_market_placebo(signal, returns, config, horizon=5, eligibility=None):
    if config.max_symbols and config.mode == "formal":
        raise ValueError("Formal placebo requires the full market: max_symbols=0")
    if config.n_placebo < 100 and config.mode != "fast":
        return {"state":"untested","reason":"99 repeats cannot attain p<0.01","tests":[],
                "stocks":0,"dates":0,"selection":"all daily eligible securities"}
    xframe = signal.iloc[len(signal)//2:].iloc[:-11]
    yframe = returns.reindex_like(xframe)
    allowed = (pd.DataFrame(True,index=xframe.index,columns=xframe.columns)
               if eligibility is None else eligibility.reindex_like(xframe).fillna(False).astype(bool))
    x = xframe.where(allowed).to_numpy(dtype=float)
    y = yframe.where(allowed).to_numpy(dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = np.where(mask,x,np.nan), np.where(mask,y,np.nan)
    counts = mask.sum(axis=1)
    coverage = {"universe_columns":x.shape[1],"observed_stocks":int(mask.any(axis=0).sum()),
                "observations":int(mask.sum()),"daily_min":int(counts.min()) if len(counts) else 0,
                "daily_median":float(np.median(counts)) if len(counts) else 0,
                "daily_max":int(counts.max()) if len(counts) else 0,
                "complete_column_filter":False,"stock_cap":None,
                "mask":"historical daily eligibility AND finite signal/return"}
    baseline = masked_ic(x,y,config.min_cross_section)
    base = {"stocks":coverage["observed_stocks"],"dates":len(x),"coverage":coverage,
            "selection":"all securities; historical daily eligibility; no complete-column filter",
            "temporal_null":"independent cyclic shifts / IAAFT within each contiguous eligible spell",
            "scope":"conditional on coverage mask; temporal exchangeability is a separate calibration requirement"}
    if len(x)<60 or baseline is None:
        return {**base,"state":"untested","reason":"insufficient daily observed cross-sections","tests":[]}
    plan = [] if config.mode == "fast" else spell_plan(x)
    base["fixed_short_observations"] = {
        "time_shift":int(sum(s.values.size for s in plan if len(s.values)<=2*horizon+1)),
        "iaaft":int(sum(s.values.size for s in plan if len(s.values)<4))}
    kinds = ("within_day",) if config.mode == "fast" else ("within_day","time_shift","iaaft")
    def task(item):
        kind_index, start, count = item
        kind = kinds[kind_index]
        null = []
        max_error = 0.
        for repeat in range(start,start+count):
            rng = np.random.default_rng(np.random.SeedSequence([config.seed,kind_index,repeat]))
            if kind == "within_day":
                surrogate = within_day_surrogate(x,rng)
            else:
                surrogate,error = temporal_surrogate(x,plan,rng,kind,horizon)
                max_error=max(max_error,error)
            value = masked_ic(surrogate,y,config.min_cross_section)
            if value is None:
                raise ValueError("A surrogate lost all valid cross-sections")
            null.append(value)
        return kind,null,max_error
    tests = []
    skipped_tests = []
    for kind_index, kind in enumerate(kinds):
        started = perf_counter()
        print(f"placebo {kind}: starting {config.n_placebo} repeats", flush=True)
        pieces = []
        batch_size = 1 if kind == "iaaft" else 10
        jobs = [(kind_index, start, min(batch_size, config.n_placebo - start))
                for start in range(0, config.n_placebo, batch_size)]
        with ThreadPoolExecutor(max_workers=config.workers) as pool:
            for offset in range(0, len(jobs), config.workers):
                pieces.extend(pool.map(task, jobs[offset:offset + config.workers]))
                completed = sum(len(part[1]) for part in pieces)
                error = max(part[2] for part in pieces)
                if kind == "iaaft" and error >= .1:
                    tests.append({"kind": kind, "state": "untested", "p": None,
                                  "spectral_error": error, "completed_repeats": completed,
                                  "null": [v for part in pieces for v in part[1]],
                                  "observed": baseline,
                                  "reason": "surrogate spectral quality gate failed"})
                    return {**base, "state": "untested", "tests": tests,
                            "reason": "invalid IAAFT surrogate; not evidence against the factor",
                            "skipped_tests": [], "stopped_early": True}
                print(f"placebo {kind}: {completed}/{config.n_placebo} "
                      f"in {perf_counter() - started:.1f}s", flush=True)
        null = [value for piece in pieces for value in piece[1]]
        error = max(piece[2] for piece in pieces)
        p = float((1 + np.count_nonzero(np.asarray(null) >= baseline)) / (len(null) + 1))
        result = {"kind": kind, "p": p, "quantile": 1 - p, "null": null,
                  "observed": baseline, "spectral_error": error if kind == "iaaft" else None,
                  "state": "pass" if p < .01 and error < .1 else "fail"}
        tests.append(result)
        # IAAFT is expensive; after a cheaper null fails, the conjunction is fixed.
        if result["state"] != "pass":
            skipped_tests = list(kinds[kind_index + 1:])
            break
    if config.mode == "fast":
        return {**base, "state": "untested", "tests": tests,
                "skipped_tests": ["time_shift", "iaaft"], "profile": "fast",
                "reason": "Exploratory diagnostic only; full placebo confirmation deferred"}
    return {**base,"state":"pass" if all(t["state"]=="pass" for t in tests) else "fail","tests":tests,"skipped_tests":skipped_tests}
