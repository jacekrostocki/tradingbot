#!/usr/bin/env python3
"""Create reproducible equity and weekly-return figures for the funding filter screen."""
from __future__ import annotations
import csv,gzip,datetime as dt
from pathlib import Path
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
def rows(path):
    op=gzip.open if path.suffix=='.gz' else open
    with op(path,'rt',encoding='utf8',newline='') as f:return list(csv.DictReader(f))
def main():
    filtered=rows(ROOT/'results'/'funding_crowding_equity.csv')
    base=rows(ROOT/'results'/'portfolio_concurrency_equity.csv.gz')
    weekly=rows(ROOT/'results'/'funding_filter_weekly_returns.csv')
    fig,ax=plt.subplots(figsize=(11,5.5))
    for data,label,style in ((base,'Baseline · base costs','--'),(filtered,'Funding filter · base costs','-')):
        z=[r for r in data if r['window']=='funding_era' and r['stress']=='False' and (r.get('config') in (None,'1pos_0.25pct'))]
        t=[dt.datetime.fromtimestamp(int(x['timestamp_ms'])/1000,dt.timezone.utc) for x in z]
        y=[float(x['equity_usd']) for x in z]
        ax.plot(t,y,linestyle=style,label=label,lw=1.6)
    ax.axhline(900,color='grey',lw=.8);ax.set_title('Kraken Futures breakout/retest: one position, funding era')
    ax.set_ylabel('Equity (USD)');ax.set_xlabel('UTC date');ax.grid(alpha=.2);ax.legend();fig.tight_layout()
    fig.savefig(ROOT/'results'/'funding_filter_equity_curve.png',dpi=160);plt.close(fig)
    vals=[float(r['weekly_return'])*100 for r in weekly if r['window']=='funding_era' and r['stress']=='False']
    vals_stress=[float(r['weekly_return'])*100 for r in weekly if r['window']=='funding_era' and r['stress']=='True']
    fig,ax=plt.subplots(figsize=(9,5))
    bins=16;ax.hist(vals,bins=bins,alpha=.62,label='Base costs');ax.hist(vals_stress,bins=bins,alpha=.62,label='Stress costs')
    ax.axvline(0,color='black',lw=.8);ax.axvline(3,color='crimson',lw=1,ls='--',label='+3% weekly target')
    ax.set_title('Weekly mark-to-market returns: funding-filtered candidate')
    ax.set_xlabel('Weekly return (%)');ax.set_ylabel('Weeks');ax.grid(axis='y',alpha=.2);ax.legend();fig.tight_layout()
    fig.savefig(ROOT/'results'/'funding_filter_weekly_distribution.png',dpi=160);plt.close(fig)
if __name__=='__main__':main()
