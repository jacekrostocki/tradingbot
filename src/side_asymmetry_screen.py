#!/usr/bin/env python3
"""Long-only versus short-only signal asymmetry screen at fixed risk."""
from __future__ import annotations
import csv,datetime as dt,hashlib,json
from pathlib import Path
from .exit_policy_screen import prep,run,WINDOWS,RISK
from .portfolio_momentum import dt_ms

ROOT=Path(__file__).resolve().parents[1]
SIDES=('both_sides','long_only','short_only')

def side_data(raw,name):
    out={};counts={}
    for asset,m in raw.items():
        sig=[s if name=='both_sides' or (name=='long_only' and s==1) or (name=='short_only' and s==-1) else 0 for s in m['sig']]
        counts[asset]={'long_signals':sum(s==1 for s in sig),'short_signals':sum(s==-1 for s in sig)};out[asset]={**m,'sig':sig}
    return out,counts

def main():
    raw=prep();variants={};signal_counts={}
    for side in SIDES:variants[side],signal_counts[side]=side_data(raw,side)
    results=[];trades=[];curves=[]
    for side,data in variants.items():
      for window,start,end in WINDOWS:
       for stress in (False,True):
        m,tr,eq=run(data,dt_ms(start),dt_ms(end),variant=side,target_r=None,max_hours=None,stress=stress)
        m.update(direction_variant=side,window=window,portfolio_risk_budget_fraction=RISK);results.append(m)
        trades += [{**x,'direction_variant':side,'window':window,'stress':stress} for x in tr]
        curves += [{**x,'direction_variant':side,'window':window,'stress':stress} for x in eq]
        print(side,window,'stress' if stress else 'base','ret',m['net_return_fraction'],'DD',m['max_drawdown_fraction'],'PF',m['profit_factor'],'n',m['trade_count'])
    out=ROOT/'results'/'side_asymmetry_screen';out.mkdir(exist_ok=True,parents=True)
    files=sorted((ROOT/'data'/'raw').glob('*_1h.csv'))+sorted((ROOT/'data'/'processed').glob('*_funding_complete_1h.csv'))
    doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'engine_sha256':hashlib.sha256(Path(__file__).with_name('exit_policy_screen.py').read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'risk_budget_fraction_total':RISK,'signal_counts':signal_counts,'method':'same breakout/retest direction logic; filter only by side; 1 position; identical stops, trailing exit, execution costs, and hard risk kill switches','results':results}
    (out/'metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for name,rows in [('trades.csv',trades),('equity.csv',curves)]:
        with (out/name).open('w',newline='',encoding='utf8') as f:
            fields=list(dict.fromkeys(k for row in rows for k in row));w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(rows)
    with (out/'metrics_summary.csv').open('w',newline='',encoding='utf8') as f:
        fields=list(results[0]);w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(results)
if __name__=='__main__':main()
