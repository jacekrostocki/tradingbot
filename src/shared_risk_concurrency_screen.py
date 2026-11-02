#!/usr/bin/env python3
"""Compare 1-4 concurrent positions under one fixed portfolio stop-risk budget."""
from __future__ import annotations
import csv,datetime as dt,hashlib,json
from pathlib import Path
from .portfolio_concurrency import prep,run
from .portfolio_momentum import ASSETS,dt_ms

ROOT=Path(__file__).resolve().parents[1]
WINDOWS=(('funding_era','2025-10-30T00:00:00Z','2026-11-02T00:00:00Z'),
         ('wf_1','2025-10-30T00:00:00Z','2026-02-01T00:00:00Z'),
         ('wf_2','2026-02-01T00:00:00Z','2026-05-22T00:00:00Z'),
         ('final_holdout_screened','2026-05-22T00:00:00Z','2026-11-02T00:00:00Z'))
TOTAL_OPEN_RISK=.0025; FUND_THRESHOLD=.00002; HOUR=3_600_000

def funding_filtered(data):
    out={}
    for a,m in data.items():
        sig=[]; blocked=unknown=0
        for i,s in enumerate(m['sig']):
            if not s:sig.append(0);continue
            rate=m['fund'].get(m['bars'][i]['timestamp_ms']-HOUR)
            if rate is None:unknown+=1;sig.append(0)
            elif s*rate>=FUND_THRESHOLD:blocked+=1;sig.append(0)
            else:sig.append(s)
        out[a]={**m,'sig':sig}
        print(a,'funding filter removed',blocked,'unpriced signal',unknown)
    return out

def main():
    raw=prep();scenarios=(('breakout_retest',raw),('breakout_retest_funding_filter',funding_filtered(raw)))
    metrics=[];trades=[];curves=[]
    for label,data in scenarios:
      for slots in (1,2,3,4):
       for name,a,b in WINDOWS:
        for stress in (False,True):
         met,tr,eq=run(data,dt_ms(a),dt_ms(b),slots=slots,risk=TOTAL_OPEN_RISK/slots,notional_cap=.75,stress=stress)
         met['strategy']=label;met['portfolio_risk_budget_fraction']=TOTAL_OPEN_RISK;met['window']=name;met['slots']=slots;metrics.append(met)
         trades += [{**x,'strategy':label,'window':name,'slots':slots,'stress':stress} for x in tr]
         curves += [{**x,'strategy':label,'window':name,'slots':slots,'stress':stress} for x in eq]
    out=ROOT/'results';out.mkdir(exist_ok=True)
    doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'data'/'raw').glob('*_1h.csv'))},'portfolio_total_open_stop_risk_fraction':TOTAL_OPEN_RISK,'funding_filter_adverse_rate_threshold':FUND_THRESHOLD,'results':metrics}
    (out/'shared_risk_concurrency_metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for fn,rows in [('shared_risk_concurrency_trades.csv',trades),('shared_risk_concurrency_equity.csv',curves)]:
      with (out/fn).open('w',newline='',encoding='utf8') as f:
        fields=list(dict.fromkeys(k for x in rows for k in x));w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    for x in metrics:
      if x['window'] in ('funding_era','final_holdout_screened'):
       print(x['strategy'],x['window'],'slots',x['slots'],'stress',x['stress'],'ret',x['net_return_fraction'],'PF',x['profit_factor'],'DD',x['max_drawdown_fraction'],'trades',x['trade_count'],'observed',x['max_observed_concurrent_positions'])
if __name__=='__main__':main()
