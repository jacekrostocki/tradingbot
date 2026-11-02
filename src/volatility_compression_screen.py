#!/usr/bin/env python3
"""Fixed volatility-compression then expansion filter on breakout/retest signals."""
from __future__ import annotations
import csv,datetime as dt,hashlib,json,statistics
from pathlib import Path
from .backtest import signals
from .portfolio_concurrency import ASSETS,INITIAL,run
from .portfolio_momentum import dt_ms,utc

ROOT=Path(__file__).resolve().parents[1]
WINDOWS=(('funding_era','2025-10-30T00:00:00Z','2026-11-02T00:00:00Z'),
         ('wf_1','2025-10-30T00:00:00Z','2026-02-01T00:00:00Z'),
         ('wf_2','2026-02-01T00:00:00Z','2026-05-22T00:00:00Z'),
         ('final_holdout_screened','2026-05-22T00:00:00Z','2026-11-02T00:00:00Z'))

def prep():
    data={}
    for a in ASSETS:
        bars,atr,trend,sig,funding=signals(a,'breakout_retest')
        original=sum(bool(x) for x in sig)
        kept=[0]*len(sig)
        # On i-1 a close confirms breakout; i is the retest. Require a quiet
        # 48h base vs 10d ATR, followed by a 25% ATR expansion on the break bar.
        for i in range(242,len(sig)):
            if not sig[i] or not atr[i-1] or atr[i-1]<=0: continue
            quiet=statistics.mean(atr[i-49:i-1])
            baseline=statistics.mean(atr[i-241:i-1])
            if quiet<=.80*baseline and atr[i-1]>=1.25*quiet:
                kept[i]=sig[i]
        data[a]={'bars':bars,'atr':atr,'trend':trend,'sig':kept,'fund':funding}
        print(a,'signals',original,'filtered',sum(bool(x) for x in kept))
    return data

def main():
    data=prep();metrics=[];trades=[];curves=[]
    for name,a,b in WINDOWS:
        for stress in (False,True):
            met,tr,eq=run(data,dt_ms(a),dt_ms(b),slots=1,risk=.0025,notional_cap=.75,stress=stress)
            met['window']=name;met['strategy']='breakout_retest_vol_compression_expansion';metrics.append(met)
            trades += [{**x,'window':name,'stress':stress} for x in tr]
            curves += [{**x,'window':name,'stress':stress} for x in eq]
    out=ROOT/'results';out.mkdir(exist_ok=True)
    doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'signal_code_sha256':hashlib.sha256((ROOT/'src'/'backtest.py').read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'data'/'raw').glob('*_1h.csv'))},'hypothesis':'A breakout/retest after a 48h ATR compression (<=80% of trailing 10d ATR) and a breakout-hour ATR expansion (>=125% of 48h mean) has better continuation odds.','results':metrics}
    (out/'volatility_compression_metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for fname,rows in [('volatility_compression_trades.csv',trades),('volatility_compression_equity.csv',curves)]:
        with (out/fname).open('w',newline='',encoding='utf8') as f:
            fields=list(dict.fromkeys(k for row in rows for k in row));w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    for x in metrics:print(x['window'],'stress' if x['stress'] else 'base',x['net_return_fraction'],'PF',x['profit_factor'],'DD',x['max_drawdown_fraction'],'trades',x['trade_count'],'fund_cov',x['funding_coverage_fraction'])
if __name__=='__main__':main()
