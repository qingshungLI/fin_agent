"""Bounded multiprocess initial feature search with one shared project audit.

Each shard owns a disjoint frozen list of initial cells and a separate output
directory. This stage is fast, non-adaptive, A-only and never grants eligibility.
The controller and workers retain the same exclusive project-lock lease.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
import gc
import json
import multiprocessing
from multiprocessing.reduction import DupFd
import os
from pathlib import Path
import re
import subprocess
import traceback

from engine.audit import AuditStore, now, write_json
from engine.cache import cached_panel, file_hash
from engine.config import ROOT, ResearchConfig
from engine.cycle import initial_tasks


def partition_cells(cells, groups):
    if not cells or groups < 1 or len(set(cells)) != len(cells):
        raise ValueError("A nonempty unique initial grid and positive group count are required")
    return [tuple(cells[i::groups]) for i in range(min(groups,len(cells)))]


def physical_cpus(budget):
    if not hasattr(os,"sched_getaffinity"):
        raise RuntimeError("Initial process placement requires Linux CPU affinity")
    allowed=os.sched_getaffinity(0)
    text=subprocess.check_output(["lscpu","-p=CPU,CORE,SOCKET"],text=True)
    seen=set();by_socket={}
    for line in text.splitlines():
        if line.startswith("#"): continue
        cpu,core,socket=map(int,line.split(","))
        if cpu in allowed and (socket,core) not in seen:
            by_socket.setdefault(socket,[]).append(cpu);seen.add((socket,core))
    ordered=[]
    for i in range(max(map(len,by_socket.values()),default=0)):
        ordered += [cpus[i] for _,cpus in sorted(by_socket.items()) if i<len(cpus)]
    if len(ordered)<budget:
        raise ValueError("Requested physical CPU budget exceeds available affinity")
    return ordered[:budget]


@contextmanager
def coordinator_lease(root):
    import fcntl
    root.mkdir(parents=True,exist_ok=True)
    handle=(root/".run.lock").open("a+b")
    try:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield handle
    finally:
        # Closing, rather than explicit LOCK_UN, retains the shared lease while
        # any running worker still owns a duplicated descriptor.
        handle.close()


def run_shard(task):
    lease=task["lease"].detach()
    try:
        os.sched_setaffinity(0,task["cpus"])
        config=ResearchConfig.model_validate(task["config"])
        if not config.initial_cells or config.mode!="fast" or config.auto_evolve:
            raise ValueError("Only frozen non-adaptive initial searches can be sharded")
        directory=Path(task["directory"]);directory.mkdir(parents=True,exist_ok=True)
        with (directory/"worker.log").open("a",buffering=1) as log:
            os.dup2(log.fileno(),1);os.dup2(log.fileno(),2)
            print(f"initial search worker {os.getpid()}: {len(config.initial_cells)} cells",flush=True)
            write_json(directory/"worker.json",{"pid":os.getpid(),"cpus":sorted(os.sched_getaffinity(0)),
                "run_id":task["run_id"],"cells":config.initial_cells,"status":"RUNNING","started_at":now()})
            from engine.pipeline import _run
            from threadpoolctl import threadpool_limits
            try:
                with threadpool_limits(limits=1):
                    state=_run(config,task["run_id"],Path(task["data_root"]),directory,
                               ROOT/"artifacts",True,False)
                result={"run_id":task["run_id"],"status":state["status"],
                        "completed":state["completed"],"attempts":state.get("attempts",0),
                        "pid":os.getpid(),"finished_at":now()}
            except Exception as exc:
                traceback.print_exc()
                result={"run_id":task["run_id"],"status":"FAILED","type":type(exc).__name__,
                        "error":str(exc),"pid":os.getpid(),"finished_at":now()}
            write_json(directory/"worker-result.json",result)
            return result
    finally:
        os.close(lease)


def summarize(campaign):
    rows=[]
    for path in sorted((campaign/"shards").glob("*/*/S-*/result.json")):
        result=json.loads(path.read_text())
        structure=result["structure"]
        primary=next(row for row in result["measurement"]["curves"]
                     if row["expression"]==1 and row["horizon"]==structure["primary_horizon"])
        rows.append({"id":result["id"],"family":result["family"],"form":result["form"],
                     "expression":structure["operational"][0],"ic":primary["mean"],
                     "cost":result["cost"],"formal":False,"source":str(path.relative_to(campaign))})
    write_json(campaign/"initial-features.json",{"stage":"initial_only","formal":False,
        "cross_shard_increment":"not_tested","candidates":rows})
    return len(rows)


def normalized_config(config):
    """Match the validated worker representation before computing cache identity."""
    return ResearchConfig.model_validate(config.model_dump())


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--run-id",required=True)
    parser.add_argument("--cpu-budget",type=int,default=40)
    parser.add_argument("--cpus-per-search",type=int,default=2)
    parser.add_argument("--data-root",type=Path,default=ROOT/"data")
    parser.add_argument("--llm-concurrency",type=int,default=8)
    args=parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}",args.run_id):
        parser.error("Invalid run ID")
    if not 1<=args.cpu_budget<=40 or not 1<=args.cpus_per_search<=8:
        parser.error("CPU budget must be 1..40; per-search budget 1..8")
    if args.cpu_budget%args.cpus_per_search:
        parser.error("CPU budget must be divisible by per-search budget")
    if not 1<=args.llm_concurrency<=20:parser.error("LLM concurrency must be 1..20")
    os.environ["AURORA_LLM_CONCURRENCY"]=str(args.llm_concurrency)
    for key in ["OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS"]:
        os.environ[key]="1"
    cpus=physical_cpus(args.cpu_budget)
    os.sched_setaffinity(0,cpus)
    cells=[f"{task.family}-F{task.form}" for task in initial_tasks()]
    group_count=args.cpu_budget//args.cpus_per_search
    memory={line.split(":")[0]:int(line.split()[1])*1024 for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:")}
    available=memory["MemAvailable"]
    capacity=max(1,(available-32*1024**3)//(32*1024**3))
    group_count=min(group_count,capacity)
    groups=partition_cells(cells,group_count)
    config=ResearchConfig(mode="fast",provider="llm",max_symbols=0,max_structures=1,
        workers=args.cpus_per_search,seed=20260908,n_boot=100,n_placebo=19,n_trees=30,n_splits=2,
        auto_evolve=False,industry_policy="strict",industry_source="rqdata_daily",data_profile="daily",
        llm_max_calls=120)
    config=normalized_config(config)
    campaign=ROOT/"artifacts"/args.run_id
    campaign.mkdir(parents=True,exist_ok=False)
    manifest={"run_id":args.run_id,"status":"PREPARING","stage":"initial_only","formal":False,
        "cpus":cpus,"cpu_budget":args.cpu_budget,"groups":groups,"available_memory_bytes":available,
        "llm_concurrency":args.llm_concurrency,"started_at":now(),"results":[],
        "source_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        "code_sha256":{p.name:file_hash(p) for p in (ROOT/"engine").glob("*.py")},
        "config":config.model_dump()}
    write_json(campaign/"campaign.json",manifest)
    with coordinator_lease(ROOT/"artifacts") as lease:
        store=AuditStore(ROOT/"artifacts")
        store.append("initial_search_started",{"run_id":args.run_id,"cells":cells,"formal":False,
                     "cpu_budget":args.cpu_budget,"manifest_hash":file_hash(campaign/"campaign.json")})
        print("preparing shared full-market daily non-ST panel",flush=True)
        panel,hit=cached_panel(args.data_root,config,ROOT/"artifacts"/"cache")
        manifest["panel"]={"shape":list(panel.fields["close"].shape),"cache_hit":hit,
            "eligible_observations":int(panel.fields["in_pool"].sum().sum()),
            "st_observations_in_pool":int((panel.fields["in_pool"] & ~panel.fields["not_st"]).sum().sum())}
        if manifest["panel"]["st_observations_in_pool"]:raise ValueError("ST eligibility violation")
        del panel;gc.collect()
        manifest["status"]="RUNNING";write_json(campaign/"campaign.json",manifest)
        context=multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=len(groups),mp_context=context) as pool:
            futures={}
            for index,coordinates in enumerate(groups):
                shard_id=f"{args.run_id}-g{index+1:02d}"
                shard_config=config.model_copy(update={"initial_cells":coordinates,"max_structures":len(coordinates)})
                ResearchConfig.model_validate(shard_config.model_dump())
                directory=campaign/"shards"/f"g{index+1:02d}"
                (directory/shard_id).mkdir(parents=True,exist_ok=False)
                (ROOT/"artifacts"/shard_id).symlink_to(directory/shard_id,target_is_directory=True)
                (ROOT/"artifacts"/"jobs").mkdir(exist_ok=True)
                (ROOT/"artifacts"/"jobs"/f"{shard_id}.log").symlink_to(directory/"worker.log")
                task={"run_id":shard_id,"config":shard_config.model_dump(),
                      "directory":str(campaign/"shards"/f"g{index+1:02d}"),
                      "data_root":str(args.data_root.resolve()),
                      "cpus":cpus[index*args.cpus_per_search:(index+1)*args.cpus_per_search],
                      "lease":DupFd(lease.fileno())}
                futures[pool.submit(run_shard,task)]=shard_id
            print(f"launched {len(groups)} feature-search processes within {len(cpus)} physical CPUs",flush=True)
            pending=set(futures)
            while pending:
                ready,pending=wait(pending,timeout=30,return_when=FIRST_COMPLETED)
                for future in ready:
                    try:
                        result=future.result()
                    except Exception as exc:
                        result={"run_id":futures[future],"status":"FAILED","type":type(exc).__name__,
                                "error":str(exc),"finished_at":now()}
                    manifest["results"].append(result)
                    print(result["run_id"],result["status"],flush=True)
                manifest["completed_features"]=summarize(campaign)
                manifest["remaining_groups"]=len(pending)
                manifest["updated_at"]=now()
                write_json(campaign/"campaign.json",manifest)
        manifest["status"]="COMPLETED" if all(r["status"]=="COMPLETED" for r in manifest["results"]) else "PARTIAL_FAILURE"
        manifest["finished_at"]=now();manifest["completed_features"]=summarize(campaign)
        write_json(campaign/"campaign.json",manifest)
        store.verify()
        store.append("initial_search_finished",{"run_id":args.run_id,"status":manifest["status"],
                     "completed_features":manifest["completed_features"],"formal":False})
    print(manifest["status"],manifest["completed_features"],flush=True)
    return 0 if manifest["status"]=="COMPLETED" else 2


if __name__=="__main__":
    raise SystemExit(main())
