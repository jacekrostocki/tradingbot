#!/usr/bin/env python3
"""Plot the screened volume-retest candidate's OOS equity and weekly returns."""
import csv,datetime as dt
from pathlib import Path
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
src=ROOT/'results'/'volume_confirmation_screen'/'equity.csv';selected=[]
with src.open(newline='',encoding='utf8') as f:
    for r in csv.DictReader(f):
        if r.get('filter')=='retest_volume_below_breakout' and r.get('window')=='final_holdout_screened':selected.append(r)
groups={}
for r in selected:
    key=r['stress'];groups.setdefault(key,[]).append((int(r['timestamp_ms']),float(r['adverse_mark_equity_usd'])))
fig,(ax1,ax2)=plt.subplots(2,1,figsize=(11,7),gridspec_kw={'height_ratios':[2,1]},constrained_layout=True)
colors={'False':'#1677b8','True':'#d17a00'};weekly={}
for stress,pts in groups.items():
    pts.sort();weekly_ends={};dates=[];vals=[]
    for t,v in pts:
        d=dt.datetime.fromtimestamp(t/1000,dt.timezone.utc);dates.append(d);vals.append(v);weekly_ends[d.isocalendar()[:2]]=(t,v)
    ax1.plot(dates,vals,label='Stress costs' if stress=='True' else 'Base costs',color=colors[stress],lw=1.7)
    prev=900.;rets=[];labels=[]
    for key,(t,v) in sorted(weekly_ends.items()):
        rets.append((v/prev-1)*100);labels.append(f'{key[0]}-W{key[1]:02d}');prev=v
    weekly[stress]=(labels,rets)
ax1.axhline(900,color='#777',lw=.8,ls='--');ax1.set_ylabel('Marked equity (USD)');ax1.set_title('Volume-retest filter: screened final window (24 weeks)');ax1.legend(frameon=False);ax1.grid(alpha=.2)
labels,base=weekly['False'];_,stress=weekly['True'];x=range(len(labels));ax2.bar([i-.2 for i in x],base,width=.4,label='Base costs',color=colors['False']);ax2.bar([i+.2 for i in x],stress,width=.4,label='Stress costs',color=colors['True']);ax2.axhline(0,color='#555',lw=.8);ax2.set_ylabel('Weekly return (%)');ax2.set_xticks(list(x));ax2.set_xticklabels(labels,rotation=55,ha='right',fontsize=8);ax2.grid(axis='y',alpha=.2);ax2.legend(frameon=False,ncol=2)
out=ROOT/'results'/'iteration_2_screened_candidate.png';out.parent.mkdir(exist_ok=True,parents=True);fig.savefig(out,dpi=170);print(out.relative_to(ROOT))
