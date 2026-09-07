"""Evaluate previously approved real-model priors without further API calls.

This is a fixed A-only evidence run, not the live proposal/evolution workflow.
Unavailable model bets remain unavailable; no probability or model output is fabricated.
"""
import json
from pathlib import Path
from time import perf_counter
import pandas as pd
from engine.audit import AuditStore,digest,now,write_json
from engine.blades import run_blades
from engine.cache import cached_panel,file_hash
from engine.catalog import Structure,register_cell,check_convergent_orientation
from engine.config import ROOT,ResearchConfig
from engine.metrics import measure_panel,power_budget
from engine.pipeline import project_lock,json_safe,stability,cost_report,publish


def main():
    config=ResearchConfig(provider="llm",data_profile="daily",industry_source="rqdata_daily",
                          industry_policy="strict",workers=6,max_structures=9,auto_evolve=False)
    root=ROOT/"artifacts";name="frozen-prior-A-01";folder=root/name
    with project_lock(root):
        folder.mkdir(exist_ok=False)
        store=AuditStore(root)
        cut_path=root/"rqdata-daily-A-03/cuts.json"
        cuts=json.loads(cut_path.read_text())
        write_json(folder/"cuts.json",cuts)
        bundle=[]
        for index,path in enumerate(sorted((root/"validation/form-priors").glob("prior-*.json"))):
            proposal=Structure.model_validate(json.loads(path.read_text()))
            proposal=proposal.model_copy(update={"id":f"S-{name}-{index+1:03d}"})
            bundle.append(proposal)
            unavailable={a.id:{"probability":None,"state":"UNAVAILABLE","reason":"DeepSeek HTTP 402; no replacement probability"} for a in proposal.assertions}
            store.freeze(name,proposal.model_dump(),unavailable)
        state={"run_id":name,"status":"RUNNING","workflow":"fixed_approved_priors_no_new_api_calls",
               "completed":[],"started_at":now(),"timings":{},
               "identity":{"config":config.model_dump(),"code":{p.name:file_hash(p) for p in (ROOT/"engine").glob("*.py")},
                           "prior_bundle":[digest(s.model_dump()) for s in bundle],"cuts":file_hash(cut_path)},
               "confirmation":{"eligible_ids":[],"B_read":False,"H_read":False}}
        write_json(folder/"checkpoint.json",state)
        store.append("fixed_prior_evaluation_started",{"run_id":name,"priors":len(bundle),"new_api_calls":0,"blind_bets":"UNAVAILABLE"})
        started=perf_counter()
        rows=[];library=[]
        try:
            store.append("A_data_read",{"run_id":name,"start":config.start,"end":config.end,"workflow":state["workflow"]})
            panel,hit=cached_panel(ROOT/"data",config,root/"cache")
            write_json(folder/"data-quality.json",panel.report)
            state["timings"]["panel_seconds"]=perf_counter()-started
            print(f"panel ready {panel.fields['close'].shape}, cache={hit}",flush=True)
            for s in bundle:
                begin=perf_counter();destination=folder/s.id
                registration=[register_cell(e,panel.fields,cuts) for e in s.operational]
                check_convergent_orientation(s,panel.fields,cuts)
                write_json(destination/"registration.json",registration)
                store.append("measurement_started",{"run_id":name,"id":s.id})
                measurement,stored=measure_panel(s,panel,config,cuts)
                print(s.id,"measured; placebo next",flush=True)
                blades=run_blades(s,panel,measurement,stored,library,config)
                primary=next(r for r in measurement["curves"] if r["expression"]==1 and r["horizon"]==s.primary_horizon)
                row=json_safe({"id":s.id,"name":s.name,"family":s.family,"form":s.form,
                    "structure":s.model_dump(),"fingerprint":digest({"expressions":sorted(s.operational),"coverage":s.coverage,"horizon":s.primary_horizon}),
                    "measurement":measurement,"blades":blades,"stability":stability(stored,s,config),
                    "cost":cost_report(stored,panel,s),"verdict":blades["verdict"],"formal":False,
                    "power":power_budget(primary["n_eff"]) if primary["n_eff"] else None,
                    "confirmation":{"eligible":False,"reasons":["Fixed prior evidence only; live blind bets and evolution unavailable"]},
                    "discovery":{"state":"NOT_RUN","reason":"fixed prior evaluation scope"},
                    "seconds":perf_counter()-begin})
                stored["signal_0"].to_parquet(destination/"research-factor.parquet")
                stored["contribution"].to_parquet(destination/"contribution.parquet")
                pd.concat({k:v.ic for k,v in stored.items() if k.startswith("ic_e")},axis=1).to_parquet(destination/"daily-ic.parquet")
                write_json(destination/"result.json",row)
                rows.append(row);state["completed"].append(s.id)
                if blades["placebo"]["state"]=="pass" and blades["verdict"]!="FAIL":library.append(stored["signal_0"])
                state["artifact_hashes"]={str(p.relative_to(folder)):file_hash(p) for p in folder.rglob("*") if p.is_file() and p.name not in {"checkpoint.json","report.md","law.md"}}
                write_json(folder/"checkpoint.json",state)
                store.append("structure_completed",{"run_id":name,"id":s.id,"result_hash":digest(row)})
                publish(root,folder,rows,panel,state,store)
                overview=json.loads((root/"overview.json").read_text())
                overview["message"]="固定真实模型提案的 A 段评估；模型盲押不可用，未运行自动演化，不授予正式 PASS"
                write_json(root/"overview.json",overview)
                print(f"{s.id}: IC={primary['mean']} placebo={blades['placebo']['state']} {row['seconds']:.1f}s",flush=True)
            assert state["identity"]["code"]=={p.name:file_hash(p) for p in (ROOT/"engine").glob("*.py")}
            state.update(status="COMPLETED",finished_at=now())
            state["timings"]["total_seconds"]=perf_counter()-started
            write_json(folder/"checkpoint.json",state)
            write_json(folder/"blind-calibration.json",{"state":"UNAVAILABLE","new_api_calls":0,"reason":"No substitute probabilities"})
            store.append("fixed_prior_evaluation_completed",{"run_id":name,"structures":len(rows),"formal":False})
            publish(root,folder,rows,panel,state,store)
            overview=json.loads((root/"overview.json").read_text())
            overview["message"]="固定真实模型提案评估完成；缺少模型盲押与自动演化，仍非正式因子"
            write_json(root/"overview.json",overview)
        except BaseException as exc:
            state["status"]="FAILED";write_json(folder/"checkpoint.json",state)
            write_json(folder/"failure.json",{"type":type(exc).__name__,"reason":str(exc),"timestamp":now()})
            store.append("fixed_prior_evaluation_failed",{"run_id":name,"error_type":type(exc).__name__})
            raise

if __name__=="__main__":main()
