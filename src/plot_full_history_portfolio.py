#!/usr/bin/env python3
"""Plot corrected full-history equity and weekly PnL screens."""
from __future__ import annotations
import csv
from datetime import datetime, timezone
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'results'/'full_history_portfolio'/'equity.csv'
OUT=ROOT/'results'/'full_history_portfolio'

def dt(ms): return datetime.fromtimestamp(int(ms)/1000,timezone.utc)

def load():
    with SRC.open(newline='',encoding='utf8') as f: rows=list(csv.DictReader(f))
    return rows

def equity_plot(rows):
    fig,ax=plt.subplots(figsize=(11,5.4))
    for strategy,stress,color,label in [
        ('breakout_retest_funding_filter','False','#1769aa','Funding filter · base'),
        ('breakout_retest_funding_filter','True','#79a9d1','Funding filter · stress'),
        ('breakout_retest','False','#d97706','Baseline · base'),
        ('breakout_retest','True','#e6b866','Baseline · stress')]:
        r=[x for x in rows if x['strategy']==strategy and x['window']=='all_3y' and x['slots']=='1' and x['stress']==stress]
        if not r: continue
        r.sort(key=lambda x:int(x['timestamp_ms']))
        r=r[::168]+([r[-1]] if r[-1] is not r[::168][-1] else [])
        ax.plot([dt(x['timestamp_ms']) for x in r],[float(x['adverse_mark_equity_usd']) for x in r],lw=1.25,color=color,label=label)
    ax.axhline(900,color='#555',lw=.8,ls='--')
    ax.set_title('Kraken Futures breakout/retest · 1 position · full 3y run')
    ax.set_ylabel('Adverse mark equity (USD)')
    ax.set_xlabel('UTC')
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4));ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.grid(alpha=.2);ax.legend(ncol=2,frameon=False);fig.tight_layout()
    fig.savefig(OUT/'equity_curve_1pos_3y.png',dpi=160);fig.savefig(OUT/'equity_curve_1pos_3y.svg');plt.close(fig)

def week_bucket(d):
    day=d.date().toordinal();return day-day%7 # Monday-based ordinal bucket

def weekly_plot(rows):
    series={}
    for strategy,stress,label in [
        ('breakout_retest_funding_filter','False','Funding filter · base'),
        ('breakout_retest_funding_filter','True','Funding filter · stress')]:
        r=[x for x in rows if x['strategy']==strategy and x['window']=='final_holdout_screened' and x['slots']=='1' and x['stress']==stress]
        r.sort(key=lambda x:int(x['timestamp_ms']))
        lasts={}
        for x in r:
            d=dt(x['timestamp_ms']);lasts[week_bucket(d)]=(d,float(x['adverse_mark_equity_usd']))
        seq=[v[1] for _,v in sorted(lasts.items())]
        series[label]=[seq[i]/seq[i-1]-1 for i in range(1,len(seq))]
    n=min(len(v) for v in series.values())
    with (OUT/'weekly_pnl_1pos_screened.csv').open('w',newline='',encoding='utf8') as f:
        w=csv.writer(f,lineterminator='\n');w.writerow(['week_number','funding_filter_base_return','funding_filter_stress_return'])
        for i in range(n):w.writerow([i+1,series['Funding filter · base'][i],series['Funding filter · stress'][i]])
    fig,ax=plt.subplots(figsize=(9.8,4.8));bins=12
    ax.hist([100*x for x in series['Funding filter · base']],bins=bins,alpha=.67,label='Base costs',color='#1769aa')
    ax.hist([100*x for x in series['Funding filter · stress']],bins=bins,alpha=.55,label='Stress costs',color='#d97706')
    ax.axvline(0,color='#333',lw=.9);ax.axvline(3,color='#a11',lw=.9,ls='--',label='+3% weekly target')
    ax.set_title('Weekly adverse mark returns · screened final period · 1 position')
    ax.set_xlabel('Weekly return (%)');ax.set_ylabel('Number of weeks');ax.grid(axis='y',alpha=.2);ax.legend(frameon=False);fig.tight_layout()
    fig.savefig(OUT/'weekly_pnl_distribution_1pos_screened.png',dpi=160);fig.savefig(OUT/'weekly_pnl_distribution_1pos_screened.svg');plt.close(fig)

def main():
    OUT.mkdir(parents=True,exist_ok=True);rows=load();equity_plot(rows);weekly_plot(rows)
if __name__=='__main__': main()
