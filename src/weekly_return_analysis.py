#!/usr/bin/env python3
"""Summarize adverse-mark weekly returns and 4-week circular block-bootstrap CIs."""
from __future__ import annotations
import argparse,csv,datetime as dt,math,random,statistics
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VALUE_KEYS={'equity_usd','adverse_mark_equity_usd','open_positions','open_stop_risk_usd','timestamp_ms'}
ID_KEYS={'strategy','variant','filter','direction_variant','slots','slots_each_side','stress','window'}

def summarize(path,initial=900.,samples=5000,seed=7):
    with path.open(newline='',encoding='utf8') as f:rows=list(csv.DictReader(f))
    if not rows:return []
    fields=set(rows[0]);ids=[x for x in ('strategy','variant','filter','direction_variant','slots','slots_each_side','stress','window') if x in fields]
    buckets={}
    for r in rows:
        key=tuple(r.get(k,'') for k in ids);t=int(float(r['timestamp_ms']));date=dt.datetime.fromtimestamp(t/1000,dt.timezone.utc);wk=date.isocalendar()[:2]
        val=float(r.get('adverse_mark_equity_usd') or r.get('equity_usd') or initial)
        buckets.setdefault(key,{}).setdefault(wk,[]).append((t,val))
    rng=random.Random(seed);out=[]
    for key,weeks in buckets.items():
        ends=[max(vals)[1] for _,vals in sorted(weeks.items())];rets=[];prev=initial
        for end in ends:rets.append(end/prev-1 if prev else 0.);prev=end
        if not rets:continue
        boot=[];n=len(rets)
        for _ in range(samples):
            draw=[]
            while len(draw)<n:
                s=rng.randrange(n);draw.extend(rets[(s+j)%n] for j in range(min(4,n)))
            boot.append(statistics.mean(draw[:n]))
        row={'source_file':str(path.relative_to(ROOT))};row.update({k:v for k,v in zip(ids,key)})
        mean=statistics.mean(rets);sd=statistics.pstdev(rets) if n>1 else 0.;downside=math.sqrt(statistics.mean(min(0.,x)**2 for x in rets))
        row.update({'weeks':n,'mean_weekly_return':mean,'median_weekly_return':statistics.median(rets),'positive_week_fraction':sum(x>0 for x in rets)/n,'worst_week_return':min(rets),'best_week_return':max(rets),'sharpe_weekly_annualized':mean/sd*math.sqrt(52) if sd else 0.,'sortino_weekly_annualized':mean/downside*math.sqrt(52) if downside else 0.,'block_bootstrap_mean_ci_2_5':sorted(boot)[int(.025*samples)],'block_bootstrap_mean_ci_97_5':sorted(boot)[int(.975*samples)],'bootstrap_block_weeks':4})
        out.append(row)
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument('inputs',nargs='+');p.add_argument('--output',default='results/weekly_return_summary.csv');p.add_argument('--samples',type=int,default=5000);a=p.parse_args();rows=[]
    for item in a.inputs:rows.extend(summarize(ROOT/item,samples=a.samples))
    fields=list(dict.fromkeys(k for r in rows for k in r))
    out=ROOT/a.output;out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('w',newline='',encoding='utf8') as f:w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(rows)
    print(f'wrote {len(rows)} grouped weekly summaries to {out.relative_to(ROOT)}')
if __name__=='__main__':main()
