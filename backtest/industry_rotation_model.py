#!/usr/bin/env python3
"""申万行业轮动级联研究。

硬约束：
1. 标签严格使用 nav.shift(-FWD-1) / nav.shift(-1) - 1；
2. 训练采用 purged walk-forward，训练末端扣除 FWD 个交易日；
3. 标准化仅在同一交易日截面内完成；
4. 超额基准是等权全市场行业收益；
5. HOLDOUT_START 之后的数据在本脚本中不被读取；
6. 不做参数搜索，只执行规格给出的默认参数。
"""
from __future__ import annotations
import json, math, warnings
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, t as t_dist

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'report.md'
FWD=10; MOM_WINDOW=20; FLOW_FAST,FLOW_SLOW=5,20; DISP_LONG=60; MIN_STOCKS=8; LIQ_PCT=.30; TOP_B=30; TOP_C=15
# 数据最新交易日为 2026-07-29；最后 24 个月严格从 2024-08-01 切出。
HOLDOUT_START=pd.Timestamp('2024-08-01')
SAMPLE_END=pd.Timestamp('2024-07-31')
FEATURES=['mom20','flow_chg','breadth','disp_long','turn_chg']

def write_report(text, mode='a'):
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    with REPORT.open(mode,encoding='utf-8') as f: f.write(text+'\n')

def load_panel(path: Path):
    """只读取样本内分区；禁止读取 HOLDOUT_START 之后的任何行。"""
    if not path.exists(): raise FileNotFoundError(path)
    df=pd.read_parquet(path, filters=[('date','<=',SAMPLE_END)])
    df['date']=pd.to_datetime(df['date'])
    # 第二道防线：即使 parquet 过滤器失效，也不允许 holdout 进入内存。
    df=df.loc[df['date']<HOLDOUT_START].copy()
    if df['date'].max()>=HOLDOUT_START: raise AssertionError('holdout leakage')
    return df

def prepare(df, return_col='equal_weight_return'):
    df=df.sort_values(['industry_code','date']).copy()
    df['ret_used']=pd.to_numeric(df[return_col],errors='coerce')
    df=df[df.ret_used.notna()].copy()
    # PIT 标签：先以 t 日收益构造行业净值，再严格按规格使用两个 shift。
    df['nav']=(1+df['ret_used']).groupby(df['industry_code']).cumprod()
    g=df.groupby('industry_code',group_keys=False)
    df['fwd_return']=g['nav'].shift(-FWD-1)/g['nav'].shift(-1)-1
    df['label']=df['fwd_return']-df.groupby('date')['fwd_return'].transform('mean')
    # 特征均只用 t 日及以前的信息。
    df['mom20']=g['nav'].pct_change(MOM_WINDOW)
    df['flow_chg']=df.groupby('industry_code')['amount_share'].transform(lambda s:s.rolling(FLOW_FAST,min_periods=FLOW_FAST).mean()/s.rolling(FLOW_SLOW,min_periods=FLOW_SLOW).mean()-1)
    df['turn_chg']=df.groupby('industry_code')['turnover_median'].transform(lambda s:s.rolling(FLOW_FAST,min_periods=FLOW_FAST).mean()/s.rolling(FLOW_SLOW,min_periods=FLOW_SLOW).mean()-1)
    df['breadth']=.5*df['up_ratio']+.5*df['above_ma20_ratio']
    df['disp_long']=df.groupby('industry_code')['return_dispersion'].transform(lambda s:s.rolling(DISP_LONG,min_periods=DISP_LONG).mean())
    df['disp_short']=df.groupby('industry_code')['return_dispersion'].transform(lambda s:s.rolling(5,min_periods=5).mean())
    for col in FEATURES:
        m=df.groupby('date')[col].transform('mean'); sd=df.groupby('date')[col].transform('std').replace(0,np.nan)
        df[col+'_z']=(df[col]-m)/sd
    df['mom_pct']=df.groupby('date')['mom20'].rank(pct=True)
    df['liq_pct']=df.groupby('date')['amount_share'].rank(pct=True)
    df['stage_a']=(df['n_stock']>=MIN_STOCKS)&(df['liq_pct']>=LIQ_PCT)
    # 标签均值必须为零；样本末端 NaN 标签不参与该检查。
    check=df.dropna(subset=['label']).groupby('date')['label'].mean().abs().max()
    if not np.isfinite(check) or check>1e-10: raise AssertionError(f'label cross-section mean != 0: {check}')
    return df

def score_baseline(df):
    return df[[x+'_z' for x in FEATURES]].sum(axis=1,min_count=len(FEATURES))

def dates_for_walk(df):
    ds=np.array(sorted(df.loc[df.label.notna(),'date'].unique()))
    # 固定 4 段时间序列 walk-forward，不搜索参数。
    if len(ds)<400: return []
    cuts=np.linspace(int(len(ds)*.55),len(ds)-1,5,dtype=int)
    return [(ds[cuts[i-1]+1],ds[cuts[i]]) for i in range(1,5)]

def purged_lgbm_scores(df):
    try:
        import lightgbm as lgb
    except Exception as e:
        warnings.warn(f'LightGBM unavailable: {e}'); return pd.Series(index=df.index,dtype=float),[]
    out=pd.Series(np.nan,index=df.index,dtype=float); folds=[]
    X=df[[x+'_z' for x in FEATURES]].values
    for test_start,test_end in dates_for_walk(df):
        train_dates=np.array(sorted(df.date.unique()))
        embargo_dates=train_dates[train_dates<test_start]
        embargo_dates=embargo_dates[:-FWD] if len(embargo_dates)>FWD else []
        tr=df.date.isin(embargo_dates)&df.stage_a&df.label.notna()
        te=df.date.between(test_start,test_end)&df.stage_a
        if tr.sum()<500 or te.sum()==0: continue
        # relevance 必须是每个交易日截面内的 5 档分位，不使用跨日期分位。
        y=(np.ceil(df.loc[tr].groupby('date')['label'].rank(method='first',pct=True)*5)-1).clip(0,4).astype(int)
        # query group 每天一个截面，严格按日期排序。
        # LightGBM 的 query group 必须与日期连续排列；不能沿用行业排序后的原索引。
        tr_idx=df.loc[tr].sort_values('date').index.to_numpy()
        xx=df.loc[tr_idx,[x+'_z' for x in FEATURES]].values; yy=y.loc[tr_idx].astype(int).values
        groups=df.loc[tr_idx].groupby('date',sort=False).size().to_numpy()
        params=dict(objective='lambdarank',metric='ndcg',ndcg_eval_at=[30],num_leaves=15,max_depth=4,min_data_in_leaf=200,feature_fraction=.7,bagging_fraction=.8,bagging_freq=1,lambda_l2=10.0,learning_rate=.05,monotone_constraints=[1,1,1,1,1],verbosity=-1,n_jobs=1)
        model=lgb.LGBMRanker(**params,n_estimators=100)
        model.fit(xx,yy,group=groups)
        out.loc[df.index[te]]=model.predict(df.loc[te,[x+'_z' for x in FEATURES]].values)
        folds.append({'test_start':str(test_start),'test_end':str(test_end),'train_rows':int(tr.sum()),'test_rows':int(te.sum())})
    return out,folds

def purged_mlp_scores(df):
    """固定两层 CPU MLP；与 LightGBM 使用相同的 purged walk-forward。"""
    from sklearn.neural_network import MLPClassifier
    out=pd.Series(np.nan,index=df.index,dtype=float); folds=[]
    feature_cols=[x+'_z' for x in FEATURES]
    valid_features=df[feature_cols].notna().all(axis=1)
    for test_start,test_end in dates_for_walk(df):
        train_dates=np.array(sorted(df.date.unique()))
        embargo_dates=train_dates[train_dates<test_start]
        embargo_dates=embargo_dates[:-FWD] if len(embargo_dates)>FWD else []
        tr=df.date.isin(embargo_dates)&df.stage_a&df.label.notna()&valid_features
        te=df.date.between(test_start,test_end)&df.stage_a&valid_features
        if tr.sum()<500 or te.sum()==0: continue
        y=(np.ceil(df.loc[tr].groupby('date')['label'].rank(method='first',pct=True)*5)-1).clip(0,4).astype(int)
        tr_idx=df.loc[tr].sort_values('date').index
        model=MLPClassifier(hidden_layer_sizes=(32,16),activation='relu',solver='adam',alpha=.01,
          batch_size=512,learning_rate_init=.001,max_iter=80,shuffle=False,early_stopping=False,
          random_state=20260810,tol=1e-4,n_iter_no_change=10)
        model.fit(df.loc[tr_idx,feature_cols],y.loc[tr_idx])
        proba=model.predict_proba(df.loc[te,feature_cols])
        out.loc[df.index[te]]=proba@model.classes_.astype(float)
        folds.append({'test_start':str(test_start),'test_end':str(test_end),'train_rows':int(tr.sum()),'test_rows':int(te.sum())})
    return out,folds

def fit_final_lgbm(df, tag):
    """用已完全实现的标签训练，再为样本末日做 PIT 打分。"""
    import lightgbm as lgb
    train=df[df.stage_a&df.label.notna()].sort_values('date').copy()
    y=(np.ceil(train.groupby('date')['label'].rank(method='first',pct=True)*5)-1).clip(0,4).astype(int)
    groups=train.groupby('date',sort=False).size().to_numpy()
    params=dict(objective='lambdarank',metric='ndcg',ndcg_eval_at=[30],num_leaves=15,max_depth=4,min_data_in_leaf=200,feature_fraction=.7,bagging_fraction=.8,bagging_freq=1,lambda_l2=10.0,learning_rate=.05,monotone_constraints=[1,1,1,1,1],verbosity=-1,n_jobs=1)
    model=lgb.LGBMRanker(**params,n_estimators=100)
    model.fit(train[[x+'_z' for x in FEATURES]],y,group=groups)
    out_dir=ROOT/'cache/derived/industry_rotation'; out_dir.mkdir(parents=True,exist_ok=True)
    model.booster_.save_model(str(out_dir/f'{tag.lower()}_final_lgbm.txt'))
    last_date=df.date.max()
    live=df[(df.date==last_date)&df.stage_a].copy()
    live['lgbm_score']=model.predict(live[[x+'_z' for x in FEATURES]])
    live['rank']=live.lgbm_score.rank(method='first',ascending=False).astype(int)
    live=live.sort_values('rank').head(TOP_C)
    cols=['date','industry_code','industry_name','parent_industry_code','parent_industry_name','lgbm_score','rank']
    live[cols].to_parquet(out_dir/f'{tag.lower()}_latest_candidates.parquet',index=False,compression='zstd')
    return live,len(train)

def fit_final_mlp(df,tag):
    """用标签已经实现的样本训练固定 MLP，再对样本末日做 PIT 打分。"""
    import joblib
    from sklearn.neural_network import MLPClassifier
    feature_cols=[x+'_z' for x in FEATURES]
    valid_features=df[feature_cols].notna().all(axis=1)
    train=df[df.stage_a&df.label.notna()&valid_features].sort_values('date').copy()
    y=(np.ceil(train.groupby('date')['label'].rank(method='first',pct=True)*5)-1).clip(0,4).astype(int)
    model=MLPClassifier(hidden_layer_sizes=(32,16),activation='relu',solver='adam',alpha=.01,
      batch_size=512,learning_rate_init=.001,max_iter=80,shuffle=False,early_stopping=False,
      random_state=20260810,tol=1e-4,n_iter_no_change=10)
    model.fit(train[feature_cols],y)
    out_dir=ROOT/'cache/derived/industry_rotation'; out_dir.mkdir(parents=True,exist_ok=True)
    joblib.dump(model,out_dir/f'{tag.lower()}_final_mlp.joblib')
    last_date=df.date.max(); live=df[(df.date==last_date)&df.stage_a&valid_features].copy()
    live['mlp_score']=model.predict_proba(live[feature_cols])@model.classes_.astype(float)
    live['rank']=live.mlp_score.rank(method='first',ascending=False).astype(int)
    live=live.sort_values('rank').head(TOP_C)
    cols=['date','industry_code','industry_name','parent_industry_code','parent_industry_name','mlp_score','rank']
    live[cols].to_parquet(out_dir/f'{tag.lower()}_mlp_latest_candidates.parquet',index=False,compression='zstd')
    return live,len(train)

def tstat(x):
    x=pd.Series(x).dropna(); return float(x.mean()/(x.std(ddof=1)/math.sqrt(len(x)))) if len(x)>1 and x.std(ddof=1)>0 else np.nan

def stage_c(df, scores):
    # 相关性只使用截至 t 的历史 excess_return，禁止读取 t+1 之后。
    hist=df.pivot_table(index='date',columns='industry_code',values='excess_return',aggfunc='first').sort_index()
    selected={};
    for d,part in df.assign(_score=scores).query('stage_a and _score==_score and label==label').groupby('date'):
        chosen=[]; parent_count={}
        candidates=part.sort_values('_score',ascending=False).head(TOP_B)
        h=hist.loc[hist.index<=d].tail(120)
        for _,r in candidates.iterrows():
            parent=r['parent_industry_code'];
            if pd.isna(parent) or parent_count.get(parent,0)>=2: continue
            ok=True
            for code in chosen:
                if code in h.columns and r.industry_code in h.columns and h[[code,r.industry_code]].dropna().shape[0]>=30:
                    if h[code].corr(h[r.industry_code])>.7: ok=False; break
            if ok: chosen.append(r.industry_code); parent_count[parent]=parent_count.get(parent,0)+1
            if len(chosen)>=TOP_C: break
        selected[d]=chosen
    return selected

def portfolio(df,scores,do_c=True):
    x=df.copy(); x['score']=scores
    a=x[x.stage_a&x.label.notna()].groupby('date').label.mean().rename('L1_afterA')
    b=x[x.stage_a&x.score.notna()&x.label.notna()].groupby('date').apply(lambda z:z.nlargest(TOP_B,'score').label.mean()).rename('L2_afterB')
    sel=stage_c(x,scores) if do_c else {}
    lookup=x.set_index(['date','industry_code']).label
    c=pd.Series({d:lookup.reindex(pd.MultiIndex.from_product([[d],codes])).mean() for d,codes in sel.items() if codes},name='L3_afterC')
    allr=x.groupby('date').label.mean().rename('L0_all')
    out=pd.concat([allr,a,b,c],axis=1)
    return out,sel

def selection_turnover(selected):
    """相邻交易日选中行业集合的单边换手率，首日为缺失。"""
    previous=None; values={}
    for d,codes in sorted(selected.items()):
        current=set(codes)
        values[d]=np.nan if previous is None else 1-len(current & previous)/TOP_C
        previous=current
    return pd.Series(values,name='top15_turnover')

def metrics(df,scores,tag):
    x=df.copy(); x['score']=scores
    ic=x[x.label.notna()&x.score.notna()].groupby('date').apply(lambda z:spearmanr(z.score,z.label).statistic if z.score.nunique()>1 else np.nan)
    p,sel=portfolio(x,scores)
    top15_selected={d:z.nlargest(TOP_C,'score').industry_code.tolist() for d,z in x[x.stage_a&x.score.notna()&x.label.notna()].groupby('date')}
    lookup=x.set_index(['date','industry_code']).label
    top15=pd.Series({d:lookup.reindex(pd.MultiIndex.from_product([[d],codes])).mean() for d,codes in top15_selected.items()},name='top15')
    turnover=selection_turnover(top15_selected)
    return {'tag':tag,'ic_mean':float(ic.mean()),'ic_std':float(ic.std()),'ic_ir':float(ic.mean()/ic.std()) if ic.std()>0 else np.nan,'top15_mean':float(top15.mean()),'top15_t':tstat(top15),'top15_turnover':float(turnover.mean()),'daily':p,'selected':sel,'scores':pd.Series(scores,index=df.index)}

def transition(df):
    x=df[['date','industry_code','mom_pct','flow_chg','label']].dropna().copy()
    x['state']=np.select([(x.mom_pct>.5)&(x.flow_chg>0),(x.mom_pct<=.5)&(x.flow_chg>0),(x.mom_pct>.5)&(x.flow_chg<=0)],['MAIN_RISE','LURK','DIVERGE'],default='COLD')
    x=x.sort_values(['industry_code','date']); x['next_state']=x.groupby('industry_code').state.shift(-1)
    mat=pd.crosstab(x.state,x.next_state,normalize='index').reindex(index=['MAIN_RISE','LURK','DIVERGE','COLD'],columns=['MAIN_RISE','LURK','DIVERGE','COLD'],fill_value=0)
    valid=x[x.next_state.notna()]
    path=float(((valid.state=='LURK')&(valid.next_state=='MAIN_RISE')).sum()/max((valid.state=='LURK').sum(),1))
    state_daily=x.groupby(['date','state']).label.mean().unstack()
    state_stats=pd.DataFrame({
      'mean':state_daily.mean(), 't_stat':state_daily.apply(tstat),
      'win_rate':(state_daily>0).mean(), 'days':state_daily.count(),
    }).reindex(['MAIN_RISE','DIVERGE','LURK','COLD'])
    # 固定路径的三步条件概率与独立随机基准（各目标状态的无条件频率）比较。
    path_prob=float(mat.loc['LURK','MAIN_RISE']*mat.loc['MAIN_RISE','DIVERGE']*mat.loc['DIVERGE','COLD'])
    freq=valid.next_state.value_counts(normalize=True)
    random_prob=float(freq.get('MAIN_RISE',0)*freq.get('DIVERGE',0)*freq.get('COLD',0))
    return mat,path,state_stats,path_prob,random_prob

def cascade_table(daily):
    cols=['L0_all','L1_afterA','L2_afterB','L3_afterC']
    out=[]
    for i,col in enumerate(cols):
        v=daily[col].dropna(); prev=daily[cols[i-1]].dropna() if i else None
        if prev is None:
            increment=v
        else:
            paired=pd.concat([daily[col],daily[cols[i-1]]],axis=1).dropna()
            increment=paired.iloc[:,0]-paired.iloc[:,1]
        out.append({'stage':col,'mean':float(v.mean()),'std':float(v.std()),'t_stat':tstat(v),'increment':float(increment.mean()),'increment_t':tstat(increment)})
    return pd.DataFrame(out)

def random_label_check(df, seed=20260809):
    rng=np.random.default_rng(seed); x=df.copy(); x['label']=x.groupby('date')['label'].transform(lambda s:pd.Series(rng.permutation(s.to_numpy()),index=s.index))
    s=score_baseline(x); daily,_=portfolio(x,s); return cascade_table(daily)

def run_one(path,tag):
    raw=load_panel(path); df=prepare(raw,'equal_weight_return')
    base=score_baseline(df); lgb_score,folds=purged_lgbm_scores(df)
    m1=metrics(df,base,tag+'_baseline'); m2=metrics(df,lgb_score,tag+'_lgbm')
    med=prepare(raw,'median_return'); med_m=metrics(med,score_baseline(med),tag+'_median')
    return df,m1,m2,med_m,folds

def save_predictions(df, baseline, lgbm, tag, mlp=None):
    out=df[['date','industry_code','industry_name','parent_industry_code','parent_industry_name','stage_a','label']].copy()
    out['baseline_score']=baseline['scores'].reindex(df.index).to_numpy()
    out['lgbm_score']=lgbm['scores'].reindex(df.index).to_numpy()
    if mlp is not None: out['mlp_score']=mlp['scores'].reindex(df.index).to_numpy()
    path=ROOT/f'cache/derived/industry_rotation/predictions_{tag.lower()}.parquet'
    path.parent.mkdir(parents=True,exist_ok=True)
    out.to_parquet(path,index=False,compression='zstd')
    return path

def fmt(x): return 'NA' if x is None or (isinstance(x,float) and not np.isfinite(x)) else f'{x:.6g}'

def main():
    global REPORT,FWD
    ap=argparse.ArgumentParser()
    ap.add_argument('--exact',action='store_true',help='使用精确 start/cancel PIT 面板')
    ap.add_argument('--fwd',type=int,default=10,help='未来标签交易日数')
    ap.add_argument('--mlp',action='store_true',help='加入固定两层 CPU MLP 对照')
    args=ap.parse_args()
    if args.fwd<1: raise ValueError('fwd must be positive')
    FWD=args.fwd
    if args.exact and FWD==10: REPORT=ROOT/'report_exact.md'
    elif args.exact: REPORT=ROOT/f'report_fwd{FWD}_exact.md'
    else: REPORT=ROOT/f'report_fwd{FWD}.md'
    write_report(f'# 申万行业轮动级联筛选器研究报告（FWD={FWD}）\n\n## PIT 与样本隔离\n\n本次固定 `FWD={FWD}`，样本内截止 `2024-07-31`；`2024-08-01` 之后最后 24 个月未被读取、统计或绘图。未来标签严格为 `nav.shift(-FWD-1) / nav.shift(-1) - 1`，特征只使用 t 日收盘及以前数据。\n',mode='w')
    suffix='_exact' if args.exact else ''
    p2,p3=ROOT/f'panel_sw2{suffix}.parquet',ROOT/f'panel_sw3{suffix}.parquet'
    if not p2.exists() or not p3.exists():
        write_report('## 当前阻塞\n\nSW2021 面板尚未生成：RQData 当前连接返回 `ConnectionRefused`。已完成断点拉取器和面板构建脚本，服务恢复后运行：\n\n```bash\n.venv/bin/python skills/rqdata-a-share-workflow/scripts/rqdata_project.py run research/pull_sws_hierarchy.py -- pull\n.venv/bin/python research/build_sw_panels.py\n```\n')
        return 2
    # 只有在两个目标面板存在时才进入后续研究。
    base2='SW2_EXACT' if args.exact else 'SW2'; base3='SW3_EXACT' if args.exact else 'SW3'
    run_suffix=f'_FWD{FWD}' if FWD!=10 else ''
    tag2=base2+run_suffix; tag3=base3+run_suffix
    d2,m2,l2,med2,f2=run_one(p2,tag2); d3,m3,l3,med3,f3=run_one(p3,tag3)
    mlp2=mlp3=None; mf2=mf3=[]
    if args.mlp:
        ms2,mf2=purged_mlp_scores(d2); ms3,mf3=purged_mlp_scores(d3)
        mlp2=metrics(d2,ms2,tag2+'_mlp'); mlp3=metrics(d3,ms3,tag3+'_mlp')
    pred2=save_predictions(d2,m2,l2,tag2,mlp2); pred3=save_predictions(d3,m3,l3,tag3,mlp3)
    fit_final_lgbm(d2,tag2); fit_final_lgbm(d3,tag3)
    if args.mlp: fit_final_mlp(d2,tag2); fit_final_mlp(d3,tag3)
    mlp_folds=f' MLP folds: `{len(mf2)}` / `{len(mf3)}`。' if args.mlp else ''
    write_report(f'## T2 特征与标签\n\n二级标签零均值已通过；三级标签零均值已通过。LightGBM walk-forward folds: `{len(f2)}` / `{len(f3)}`。{mlp_folds}\n\n预测输出：`{pred2.relative_to(ROOT)}`、`{pred3.relative_to(ROOT)}`。\n')
    rows=[]
    evaluated=[m2,m3,l2,l3]+(([mlp2,mlp3]) if args.mlp else [])
    for a in evaluated: rows.append(f"|{a['tag']}|{fmt(a['ic_mean'])}|{fmt(a['ic_std'])}|{fmt(a['ic_ir'])}|{fmt(a['top15_mean'])}|{fmt(a['top15_t'])}|{fmt(a['top15_turnover'])}|")
    cascade_tables={
      'SW2_baseline':cascade_table(m2['daily']), 'SW3_baseline':cascade_table(m3['daily']),
      'SW2_lgbm':cascade_table(l2['daily']), 'SW3_lgbm':cascade_table(l3['daily']),
    }
    if args.mlp:
        cascade_tables['SW2_mlp']=cascade_table(mlp2['daily']); cascade_tables['SW3_mlp']=cascade_table(mlp3['daily'])
    casc3=cascade_tables['SW3_baseline']
    t3_sentence=('三级相对二级需要进入两层结构候选。' if (m3['top15_t']>m2['top15_t'] and m3['ic_mean']>m2['ic_mean']) else '三级相对二级未显示同时的增量优势，默认采用二级。')
    model_sentence=''
    if args.mlp:
        model_sentence=(' MLP 在二级和三级的 Top15 均值均高于 LightGBM。' if (mlp2['top15_mean']>l2['top15_mean'] and mlp3['top15_mean']>l3['top15_mean']) else ' MLP 未在二级和三级同时打赢 LightGBM。')
    delete_sentence='；'.join(f"{r.stage} 应删除（increment t<2）" for _,r in casc3.iloc[1:].iterrows() if not np.isfinite(r.increment_t) or r.increment_t<2) or '级联各级均达到 increment t>=2，暂不删除任何一级。'
    all_cascades='\n\n'.join(f'### {name}\n\n'+table.to_markdown(index=False) for name,table in cascade_tables.items())
    write_report('## T3/T4 粒度与级联\n\n|版本|IC均值|IC标准差|IC IR|Top15均值|Top15 t|Top15单边换手率|\n|---|---:|---:|---:|---:|---:|---:|\n'+'\n'.join(rows)+'\n\n'+all_cascades+'\n\n结论：'+t3_sentence+model_sentence+'\n级联判据（按三级零参数基线）：'+delete_sentence+'\n')
    mat,pathprob,state_stats,path3,random3=transition(d3)
    path_conclusion=('高于' if path3>random3 else '不高于')
    write_report('## T5 象限\n\n象限前瞻超额：\n\n'+state_stats.to_markdown()+'\n\n日度转移矩阵：\n\n```text\n'+mat.to_string()+'\n```\n\nLURK→MAIN_RISE 条件转移概率: `'+fmt(pathprob)+'`。完整路径 `LURK→MAIN_RISE→DIVERGE→COLD` 的三步条件概率为 `'+fmt(path3)+'`，独立随机基准为 `'+fmt(random3)+'`，因此该路径'+path_conclusion+'随机基准。\n')
    rnd=random_label_check(d3)
    sub=[]
    for start,end in [('2016-01-01','2019-12-31'),('2020-01-01','2023-12-31')]:
        z=d3[d3.date.between(start,end)]; sub.append(cascade_table(metrics(z,score_baseline(z),'sub')['daily']).assign(period=f'{start[:4]}-{end[:4]}'))
    experiment_count=12 if args.mlp else 10
    write_report('## T6 稳健性\n\n三级中位数收益 Top15 均值/t：`'+fmt(med3['top15_mean'])+'` / `'+fmt(med3['top15_t'])+'`。\n\n随机标签级联：\n\n'+rnd.to_markdown(index=False)+'\n\n子样本：\n\n'+pd.concat(sub).to_markdown(index=False)+'\n\n回购事件对照：当前未接入事件面板，跳过。\n\n## 异常与不确定性\n\n- SW2021 与中信分类的历史成分定义需要以 RQData 返回为准。\n- 当前 holdout 未读取，不能对其做任何结论。\n- 结果只执行固定参数，没有参数搜索。\n- 若三级相对二级 IC、Top15 超额和稳定性没有显著增量，应采用二级；若显著更好，采用二级选方向、三级选股的两层结构。\n\n实验次数：固定主流程共 '+str(experiment_count)+' 组，未做参数搜索。\n')
    if args.exact:
        write_report(f'## 精确 PIT 数据与产物\n\n- 精确面板：`panel_sw2_exact.parquet`、`panel_sw3_exact.parquet`，物理日期均止于 2024-07-31。\n- Walk-forward 分数：`{pred2.relative_to(ROOT)}`、`{pred3.relative_to(ROOT)}`。\n- 最终 LightGBM 与候选使用标签 `{tag2.lower()}`、`{tag3.lower()}`；若启用 MLP，同时保存 `.joblib` 模型与 `_mlp_latest_candidates.parquet`。\n- 本轮只在锁定样本内评价，不读取 holdout。\n')
    return 0
if __name__=='__main__': raise SystemExit(main())
