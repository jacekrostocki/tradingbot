#!/usr/bin/env python3
"""Volume confirmation for breakout/retest, with a fixed 0.25% risk budget."""
from __future__ import annotations
import csv,datetime as dt,hashlib,json,statistics
from pathlib import Path
from .exit_policy_screen import prep,run,WINDOWS,RISK
from .portfolio_momentum import dt_ms

ROOT=Path(__file__).resolve().parents[1]
FILTERS=('baseline','breakout_volume_1_5x_prior_24h_median','retest_volume_below_breakout','both_volume_conditions')
VOL_MULTIPLE=1.5;LOOKBACK=24

def apply_filter(raw,name):
    out={};counts={'volume_breakout_rejects':0,'retest_volume_rejects':0,'unknown':0,'signals_kept':0}
    for asset,m in raw.items():
        sig=[];vol=[b.get('volume') for b in m['bars']]
        for i,side in enumerate(m['sig']):
            if not side:sig.append(0);continue
            allow=True
            if name in ('breakout_volume_1_5x_prior_24h_median','both_volume_conditions'):
                ref=vol[max(0,i-LOOKBACK-1):i-1]
                if i<LOOKBACK+1 or not ref or vol[i-1] is None:
                    counts['unknown']+=1;allow=False
                else:
                    med=statistics.median(ref)
                    if med<=0 or vol[i-1]<VOL_MULTIPLE*med:
                        counts['volume_breakout_rejects']+=1;allow=False
            if name in ('retest_volume_below_breakout','both_volume_conditions'):
                if vol[i] is None or vol[i-1] is None:
                    counts['unknown']+=1;allow=False
                elif vol[i]>=vol[i-1]:
                    counts['retest_volume_rejects']+=1;allow=False
            sig.append(side if allow else 0)
        counts['signals_kept']+=sum(bool(x) for x in sig)
        out[asset]={**m,'sig':sig}
    return out,counts

def main():
    raw=prep();datasets={};filters={}
    for name in FILTERS:
        datasets[name],filters[name]=apply_filter(raw,name);print(name,filters[name])
    results=[];trades=[];curves=[]
    for name,data in datasets.items():
      for window,start,end in WINDOWS:
       for stress in (False,True):
        m,tr,eq=run(data,dt_ms(start),dt_ms(end),variant=name,target_r=None,max_hours=None,stress=stress)
        m.update(filter=name,window=window,portfolio_risk_budget_fraction=RISK);results.append(m)
        trades += [{**x,'filter':name,'window':window,'stress':stress} for x in tr]
        curves += [{**x,'filter':name,'window':window,'stress':stress} for x in eq]
        print(name,window,'stress' if stress else 'base','ret',m['net_return_fraction'],'DD',m['max_drawdown_fraction'],'PF',m['profit_factor'],'n',m['trade_count'])
    out=ROOT/'results'/'volume_confirmation_screen';out.mkdir(exist_ok=True,parents=True)
    files=sorted((ROOT/'data'/'raw').glob('*_1h.csv'))+sorted((ROOT/'data'/'processed').glob('*_funding_complete_1h.csv'))
    doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'engine_sha256':hashlib.sha256(Path(__file__).with_name('exit_policy_screen.py').read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'volume_definition':'executed volume on closed 1h OHLCV candle; breakout candle is prior bar i-1, retest/signal candle is i','breakout_volume_threshold_multiple_of_prior_24h_median':VOL_MULTIPLE,'total_open_risk_budget_fraction':RISK,'filters':filters,'results':results}
    (out/'metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for name,rows in [('trades.csv',trades),('equity.csv',curves)]:
        with (out/name).open('w',newline='',encoding='utf8') as f:
            fields=list(dict.fromkeys(k for row in rows for k in row));w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(rows)
    with (out/'metrics_summary.csv').open('w',newline='',encoding='utf8') as f:
        fields=list(results[0]);w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(results)
if __name__=='__main__':main()
