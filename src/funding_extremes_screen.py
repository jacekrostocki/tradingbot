#!/usr/bin/env python3
"""Funding-extreme events with trend-confirmed direction and fixed portfolio risk."""
from __future__ import annotations
import bisect,csv,datetime as dt,hashlib,json,math
from pathlib import Path
from .exit_policy_screen import prep,run,WINDOWS,RISK
from .portfolio_momentum import dt_ms

ROOT=Path(__file__).resolve().parents[1]
HOUR=3_600_000;LOOKBACK_HOURS=720;MIN_HISTORY=600;TAIL=.05

def percentile(values,p):
    x=sorted(values);k=(len(x)-1)*p;lo=int(k);hi=min(lo+1,len(x)-1);frac=k-lo
    return x[lo]*(1-frac)+x[hi]*frac

def funding_signal_data(raw):
    out={};counts={}
    for asset,m in raw.items():
        times=sorted(m['fund']);values=[m['fund'][t] for t in times];sig=[0]*len(m['sig']);high=low=unknown=0
        for i,b in enumerate(m['bars']):
            rate_ts=b['timestamp_ms']-HOUR
            k=bisect.bisect_left(times,rate_ts)
            if k>=len(times) or times[k]!=rate_ts:unknown+=1;continue
            lo=bisect.bisect_left(times,rate_ts-LOOKBACK_HOURS*HOUR)
            hist=values[lo:k]
            if len(hist)<MIN_HISTORY:continue
            qlo=percentile(hist,TAIL);qhi=percentile(hist,1-TAIL)
            previous=m['fund'].get(rate_ts-HOUR)
            current=values[k]
            if previous is None:unknown+=1;continue
            if current>max(0.,qhi) and previous<=qhi:
                sig[i]=-1;high+=1
            elif current<min(0.,qlo) and previous>=qlo:
                sig[i]=1;low+=1
        out[asset]={**m,'sig':sig}
        counts[asset]={'positive_extreme_events':high,'negative_extreme_events':low,'unknown_prior_rates':unknown,'total_events':high+low}
    return out,counts

def main():
    raw=prep();data,event_counts=funding_signal_data(raw);results=[];trades=[];curves=[]
    for window,start,end in WINDOWS:
      for stress in (False,True):
        m,tr,eq=run(data,dt_ms(start),dt_ms(end),variant='funding_extreme_contrarian_trend_confirmed',target_r=None,max_hours=None,stress=stress)
        m.update(strategy='funding_extreme_contrarian_trend_confirmed',window=window,portfolio_risk_budget_fraction=RISK)
        results.append(m);trades += [{**x,'window':window,'stress':stress} for x in tr];curves += [{**x,'window':window,'stress':stress} for x in eq]
        print(window,'stress' if stress else 'base','return',m['net_return_fraction'],'DD',m['max_drawdown_fraction'],'PF',m['profit_factor'],'n',m['trade_count'])
    out=ROOT/'results'/'funding_extremes_screen';out.mkdir(exist_ok=True,parents=True)
    files=sorted((ROOT/'data'/'raw').glob('*_1h.csv'))+sorted((ROOT/'data'/'processed').glob('*_funding_complete_1h.csv'))
    doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'engine_sha256':hashlib.sha256(Path(__file__).with_name('exit_policy_screen.py').read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'hypothesis':'A new 95th/5th percentile trailing 30-day funding-rate extreme, computed without the current observation, marks crowded positioning; enter contrarian only on a threshold crossing and only when 4h trend and 30d side-adjusted momentum confirm the contrarian direction. Funding-rate rank is pair-specific; all threshold history is lagged.','funding_rolling_history_hours':LOOKBACK_HOURS,'minimum_history_observations':MIN_HISTORY,'extreme_percentile':TAIL,'risk_budget_fraction_total':RISK,'event_counts':event_counts,'results':results}
    (out/'metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for name,rows in [('trades.csv',trades),('equity.csv',curves)]:
        with (out/name).open('w',newline='',encoding='utf8') as f:
            fields=list(dict.fromkeys(k for row in rows for k in row));w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(rows)
    with (out/'metrics_summary.csv').open('w',newline='',encoding='utf8') as f:
        fields=list(results[0]);w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(results)
if __name__=='__main__':main()
