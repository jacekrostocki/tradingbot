#!/usr/bin/env python3
"""Summarize weekly uncertainty and trade stats for the fixed funding-filter screen."""
from __future__ import annotations
import csv,datetime as dt,gzip,json,math,random,statistics
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WINDOWS=('funding_era','wf_1','wf_2','final_holdout_screened')
def readrows(p):
    op=gzip.open if p.suffix=='.gz' else open
    with op(p,'rt',encoding='utf8',newline='') as f:return list(csv.DictReader(f))
def main():
    curves=readrows(ROOT/'results'/'funding_crowding_equity.csv')
    trades=readrows(ROOT/'results'/'funding_crowding_trades.csv')
    weekly=[];summary=[]
    for window in WINDOWS:
      for stress in (False,True):
        rows=[r for r in curves if r['window']==window and r['stress'].lower()==str(stress).lower()]
        weekmarks={}
        for r in rows:
            d=dt.datetime.fromtimestamp(int(r['timestamp_ms'])/1000,dt.timezone.utc).date()
            weekmarks[d.isocalendar()[:2]]=float(r['adverse_mark_equity_usd'])
        keys=sorted(weekmarks);rets=[]
        for i in range(1,len(keys)):
            r=weekmarks[keys[i]]/weekmarks[keys[i-1]]-1
            rets.append(r);weekly.append({'window':window,'stress':stress,'iso_week':f'{keys[i][0]}-W{keys[i][1]:02d}','weekly_return':r})
        n=len(rets)
        if n==0:continue
        down=[min(0.,x) for x in rets];sd=statistics.pstdev(rets)
        downside=math.sqrt(sum(x*x for x in down)/n)
        rng=random.Random(42026);boot=[];block=4
        for _ in range(5000):
            sample=[]
            while len(sample)<n:
                start=rng.randrange(n)
                sample.extend(rets[(start+j)%n] for j in range(block))
            boot.append(statistics.mean(sample[:n]))
        boot.sort();bytrade=[float(x['net']) for x in trades if x['window']==window and x['stress'].lower()==str(stress).lower()]
        summary.append({'window':window,'stress':stress,'weeks':n,'weekly_mean':statistics.mean(rets),'weekly_median':statistics.median(rets),'weekly_positive_fraction':sum(x>0 for x in rets)/n,'weekly_ge_3pct_count':sum(x>=.03 for x in rets),'weekly_worst':min(rets),'weekly_best':max(rets),'weekly_sharpe_ann_approx':statistics.mean(rets)/sd*math.sqrt(52) if sd else 0,'weekly_sortino_ann_approx':statistics.mean(rets)/downside*math.sqrt(52) if downside else None,'block_bootstrap_95pct_mean_ci_low':boot[int(.025*len(boot))],'block_bootstrap_95pct_mean_ci_high':boot[int(.975*len(boot))],'trades':len(bytrade),'trade_win_rate':sum(x>0 for x in bytrade)/len(bytrade) if bytrade else 0,'trade_expectancy_usd':statistics.mean(bytrade) if bytrade else 0})
    for name,rows in [('funding_filter_weekly_returns.csv',weekly),('funding_filter_weekly_summary.csv',summary)]:
      with (ROOT/'results'/name).open('w',newline='',encoding='utf8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    (ROOT/'results'/'funding_filter_weekly_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    for x in summary:
      if x['window'] in ('funding_era','final_holdout_screened'):
       print(x)
if __name__=='__main__':main()
