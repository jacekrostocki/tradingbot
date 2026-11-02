#!/usr/bin/env python3
"""Cross-asset filters for correlated crypto breakout signals.
Filters are fixed ex ante: BTC 4H trend agreement and 30d relative strength.
The entry/exit engine, execution costs, and shared risk budget stay unchanged.
"""
from __future__ import annotations
import csv,datetime as dt,hashlib,json
from pathlib import Path
from .exit_policy_screen import prep,run,WINDOWS,RISK
from .portfolio_momentum import MOMENTUM_LOOKBACK,dt_ms

ROOT=Path(__file__).resolve().parents[1]
FILTERS=('baseline','btc_4h_trend_agreement','relative_strength_vs_btc_30d','combined')

def filtered_data(raw,filter_name):
    btc=raw['BTC'];btc_close=[b['close'] for b in btc['bars']];out={};counts={'blocked_btc_trend':0,'blocked_relative_strength':0,'unknown':0}
    for asset,m in raw.items():
        sig=[]
        for i,side in enumerate(m['sig']):
            if not side:sig.append(0);continue
            allow=True
            if filter_name in ('btc_4h_trend_agreement','combined') and btc['trend'][i]!=side:
                counts['blocked_btc_trend']+=1;allow=False
            if filter_name in ('relative_strength_vs_btc_30d','combined') and asset!='BTC':
                j=i-MOMENTUM_LOOKBACK
                if j<0 or btc_close[j]<=0 or m['bars'][j]['close']<=0:
                    counts['unknown']+=1;allow=False
                else:
                    rel=(m['bars'][i]['close']/m['bars'][j]['close']-1)-(btc_close[i]/btc_close[j]-1)
                    if side*rel<=0:counts['blocked_relative_strength']+=1;allow=False
            sig.append(side if allow else 0)
        out[asset]={**m,'sig':sig}
    counts['signals_kept']=sum(bool(x) for m in out.values() for x in m['sig'])
    return out,counts

def main():
    raw=prep();datasets={};filters={}
    for name in FILTERS:
        datasets[name],filters[name]=filtered_data(raw,name)
        print(name,filters[name])
    results=[];trades=[];curves=[]
    for filter_name,data in datasets.items():
      for window,start,end in WINDOWS:
       for stress in (False,True):
        m,tr,eq=run(data,dt_ms(start),dt_ms(end),variant=filter_name,target_r=None,max_hours=None,stress=stress)
        m.update(filter=filter_name,window=window,portfolio_risk_budget_fraction=RISK)
        results.append(m);trades += [{**x,'filter':filter_name,'window':window,'stress':stress} for x in tr]
        curves += [{**x,'filter':filter_name,'window':window,'stress':stress} for x in eq]
        print(filter_name,window,'stress' if stress else 'base','ret',m['net_return_fraction'],'DD',m['max_drawdown_fraction'],'PF',m['profit_factor'],'n',m['trade_count'])
    out=ROOT/'results'/'cross_asset_screen';out.mkdir(exist_ok=True,parents=True)
    files=sorted((ROOT/'data'/'raw').glob('*_1h.csv'))+sorted((ROOT/'data'/'processed').glob('*_funding_complete_1h.csv'))
    doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'engine_sha256':hashlib.sha256(Path(__file__).with_name('exit_policy_screen.py').read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'risk_budget_fraction_total':RISK,'filters':filters,'method':'fixed 1h breakout/retest entries and 4h trend filter; one position at a time; 30d side-adjusted momentum rank; only predeclared cross-asset filters; no tuning on screened final period','results':results}
    (out/'metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for name,rows in [('trades.csv',trades),('equity.csv',curves)]:
        with (out/name).open('w',newline='',encoding='utf8') as f:
            fields=list(dict.fromkeys(k for row in rows for k in row));w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(rows)
    with (out/'metrics_summary.csv').open('w',newline='',encoding='utf8') as f:
        fields=list(results[0]);w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(results)
if __name__=='__main__':main()
