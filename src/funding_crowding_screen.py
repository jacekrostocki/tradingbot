#!/usr/bin/env python3
"""Test a preregistered adverse-funding crowding filter on breakout/retest."""
from __future__ import annotations
import csv,datetime as dt,hashlib,json
from pathlib import Path
from .backtest import signals
from .portfolio_concurrency import ASSETS,run
from .portfolio_momentum import dt_ms

ROOT=Path(__file__).resolve().parents[1]
def hashes():
    paths=sorted((ROOT/'data'/'raw').glob('*_1h.csv'))+sorted((ROOT/'data'/'processed').glob('*_funding_complete_1h.csv'))
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
WINDOWS=(('funding_era','2025-10-30T00:00:00Z','2026-11-02T00:00:00Z'),
         ('wf_1','2025-10-30T00:00:00Z','2026-02-01T00:00:00Z'),
         ('wf_2','2026-02-01T00:00:00Z','2026-05-22T00:00:00Z'),
         ('final_holdout_screened','2026-05-22T00:00:00Z','2026-11-02T00:00:00Z'))
ADVERSE_FUNDING_THRESHOLD=.00002
HOUR=3_600_000

def prep():
    data={}
    for a in ASSETS:
        bars,atr,trend,sig,funding=signals(a,'breakout_retest')
        kept=[0]*len(sig);blocked=missing=0
        for i,s in enumerate(sig):
            if not s:continue
            # Use only the last completed funding observation available at the signal close.
            r=funding.get(bars[i]['timestamp_ms']-HOUR)
            if r is None:missing+=1;continue
            if s*r>=ADVERSE_FUNDING_THRESHOLD:blocked+=1;continue
            kept[i]=s
        data[a]={'bars':bars,'atr':atr,'trend':trend,'sig':kept,'fund':funding}
        print(a,'kept',sum(bool(x) for x in kept),'blocked_adverse',blocked,'unknown_skipped',missing)
    return data

def main():
    data=prep();metrics=[];trades=[];curves=[]
    for name,a,b in WINDOWS:
      for stress in (False,True):
        m,tr,eq=run(data,dt_ms(a),dt_ms(b),slots=1,risk=.0025,notional_cap=.75,stress=stress)
        m['window']=name;m['strategy']='breakout_retest_adverse_funding_filtered';metrics.append(m)
        trades += [{**x,'window':name,'stress':stress} for x in tr]
        curves += [{**x,'window':name,'stress':stress} for x in eq]
    out=ROOT/'results';out.mkdir(exist_ok=True)
    doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'signal_code_sha256':hashlib.sha256((ROOT/'src'/'backtest.py').read_bytes()).hexdigest(),'data_sha256':hashes(),'hypothesis':'Avoid an otherwise valid breakout/retest when the last already-observed funding rate implies a >=0.2 basis point/hour funding payment for the proposed side; missing rates cause candidate rejection.','threshold':ADVERSE_FUNDING_THRESHOLD,'threshold_unit':'relative rate per hour; 0.00002 = 0.2 basis point/hour','results':metrics}
    (out/'funding_crowding_metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for fname,rows in [('funding_crowding_trades.csv',trades),('funding_crowding_equity.csv',curves)]:
        with (out/fname).open('w',newline='',encoding='utf8') as f:
            fields=list(dict.fromkeys(k for x in rows for k in x));w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(rows)
    for x in metrics:print(x['window'],'stress' if x['stress'] else 'base',x['net_return_fraction'],'PF',x['profit_factor'],'DD',x['max_drawdown_fraction'],'n',x['trade_count'])
if __name__=='__main__':main()
