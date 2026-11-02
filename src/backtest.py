#!/usr/bin/env python3
"""Reproducible OHLCV research backtester. No exchange execution code."""
from __future__ import annotations
import argparse, csv, datetime as dt, hashlib, json, math, statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def read(path):
    with path.open(newline="",encoding="utf8") as f: return list(csv.DictReader(f))
def ema(xs,n):
    out=[None]*len(xs); alpha=2/(n+1); prev=None
    for i,x in enumerate(xs):
        prev=x if prev is None else alpha*x+(1-alpha)*prev; out[i]=prev
    return out
def atr(rows,n=14):
    out=[None]*len(rows); tr=[]
    for i,r in enumerate(rows):
        h,l,c=float(r['high']),float(r['low']),float(r['close'])
        prev=float(rows[i-1]['close']) if i else c
        tr.append(max(h-l,abs(h-prev),abs(l-prev)))
        if i>=n-1: out[i]=sum(tr[i-n+1:i+1])/n
    return out
def load(asset):
    raw=ROOT/'data'/'raw'; h1=read(raw/f'kraken_futures_{asset}_1h.csv'); h4=read(raw/f'kraken_futures_{asset}_4h.csv')
    # Prefer the merged official historical export + current public API tail;
    # retain the original raw API capture as fallback and provenance.
    funding_path=ROOT/'data'/'processed'/f'kraken_futures_{asset}_funding_complete_1h.csv'
    if not funding_path.exists(): funding_path=raw/f'kraken_futures_{asset}_funding_1h.csv'
    funding={int(x['timestamp_ms']):float(x['funding_rate']) for x in read(funding_path)} if funding_path.exists() else {}
    for x in h1+h4:
        for k in ('timestamp_ms','open','high','low','close','volume'): x[k]=int(x[k]) if k=='timestamp_ms' else float(x[k])
    return h1,h4,funding
def trend_filter(h1,h4):
    # 4H signals become available only after the 4H candle closes; align to the first 1H bar at/after close.
    close=[x['close'] for x in h4]; fast,slow=ema(close,50),ema(close,200); trend={}
    for i,r in enumerate(h4):
        available=int(r['timestamp_ms'])+4*3600*1000
        if i>=199: trend[available]=1 if fast[i]>slow[i] and close[i]>slow[i] else (-1 if fast[i]<slow[i] and close[i]<slow[i] else 0)
    vals=sorted(trend.items()); out=[]; j=0; direction=0
    for r in h1:
        t=r['timestamp_ms']
        while j<len(vals) and vals[j][0]<=t: direction=vals[j][1]; j+=1
        out.append(direction)
    return out
def signals(asset, strategy):
    h1,h4,funding=load(asset); close=[r['close'] for r in h1]; high=[r['high'] for r in h1]; low=[r['low'] for r in h1]
    a=atr(h1); e20=ema(close,20); trend=trend_filter(h1,h4); sig=[0]*len(h1)
    for i in range(201,len(h1)-1):
        if not a[i] or a[i]<=0: continue
        d=trend[i]
        if strategy=='trend_donchian':
            hi=max(high[i-24:i]); lo=min(low[i-24:i])
            sig[i]=1 if d==1 and close[i]>hi else (-1 if d==-1 and close[i]<lo else 0)
        elif strategy=='momentum_structure':
            higher_lows=low[i]>low[i-1]>low[i-2]; lower_highs=high[i]<high[i-1]<high[i-2]
            sig[i]=1 if d==1 and close[i]>e20[i] and close[i]>close[i-4] and higher_lows else (-1 if d==-1 and close[i]<e20[i] and close[i]<close[i-4] and lower_highs else 0)
        elif strategy=='breakout_retest':
            # A confirmed break of the prior 24-bar range, then a retest/close back on the breakout side.
            long_level=max(high[i-25:i-1]); short_level=min(low[i-25:i-1])
            for direction,level in ((1,long_level),(-1,short_level)):
                if direction!=d: continue
                broke=close[i-1]>max(high[i-25:i-1]) if direction==1 else close[i-1]<min(low[i-25:i-1])
                touched=low[i]<=level+0.25*a[i] if direction==1 else high[i]>=level-0.25*a[i]
                held=close[i]>level if direction==1 else close[i]<level
                if broke and touched and held: sig[i]=direction
        elif strategy=='ema_pullback':
            prev_below=close[i-1]<e20[i-1]; prev_above=close[i-1]>e20[i-1]
            sig[i]=1 if d==1 and prev_below and close[i]>e20[i] and close[i]>close[i-2] else (-1 if d==-1 and prev_above and close[i]<e20[i] and close[i]<close[i-2] else 0)
        else: raise ValueError(strategy)
    return h1,a,trend,sig,funding
def run(asset,strategy,split,stress=False):
    h1,ats,trends,sigs,funding=signals(asset,strategy); n=len(h1)
    start=int(n*split[0]); stop=int(n*split[1]); equity=900.; peak=equity; dd=0.; trades=[]; pos=None; fee=.0005
    spread=.000375 if stress else .00015; slippage=.000375 if stress else .00015; friction=spread+slippage
    funding_covered=sum(1 for r in h1[start:stop] if r['timestamp_ms'] in funding)
    daily={}; weekly={}; halted_dates=set(); eq_curve=[]; rejections=0
    for i in range(max(start,201),min(stop,n-1)):
        r=h1[i]; t=r['timestamp_ms']; day=t//86400000; week=t//(7*86400000)
        o,hi,lo,c=r['open'],r['high'],r['low'],r['close']
        if pos:
            if t in funding: pos['funding'] += -pos['side']*funding[t]*pos['qty']*pos['entry']
            else: pos['funding_missing_hours'] += 1
            stop_hit=(lo<=pos['stop'] if pos['side']==1 else hi>=pos['stop'])
            reverse=trends[i] == -pos['side']
            exit_price=None; reason=''
            if stop_hit: exit_price=pos['stop']; reason='stop'
            elif reverse: exit_price=o; reason='trend_flip'
            else:
                favorable=(hi-pos['entry'] if pos['side']==1 else pos['entry']-lo)
                if favorable>=pos['risk_dist']: pos['trail_active']=True
                if pos['trail_active']:
                    candidate=(pos['extreme']-3*ats[i] if pos['side']==1 else pos['extreme']+3*ats[i])
                    pos['stop']=max(pos['stop'],candidate) if pos['side']==1 else min(pos['stop'],candidate)
                pos['extreme']=max(pos['extreme'],hi) if pos['side']==1 else min(pos['extreme'],lo)
                # Close-of-bar trailing updates take effect from the next bar; stop check was before update.
                if i==stop-1: exit_price=c; reason='period_end'
            if exit_price is not None:
                px=exit_price*(1-friction*pos['side']); gross=pos['side']*(px-pos['entry'])*pos['qty']; fees=pos['qty']*(pos['entry']+px)*fee
                net=gross-fees+pos['funding']; equity+=net; peak=max(peak,equity); dd=min(dd,(equity/peak)-1); pos.update(exit_ms=t,exit=px,gross=gross,fees=fees,net=net,reason=reason,equity=equity)
                trades.append(pos); pos=None
        # Include conservative intrabar unrealized equity in drawdown and entry halts.
        mark=equity
        if pos:
            adverse=lo if pos['side']==1 else hi
            mark += pos['side']*(adverse-pos['entry'])*pos['qty'] - pos['qty']*(pos['entry']+adverse)*fee + pos['funding']
        peak=max(peak,mark); dd=min(dd,mark/peak-1)
        if day not in daily: daily[day]=mark
        if week not in weekly: weekly[week]=mark
        if pos is None and i<stop-1 and sigs[i] and (mark/daily[day]-1)>-.01 and (mark/weekly[week]-1)>-.03 and (mark/peak-1)>-.06:
            side=sigs[i]; entry=h1[i+1]['open']*(1+friction*side); dist=2*ats[i]
            if not math.isfinite(dist) or dist<=0: continue
            risk_frac=dist/entry+2*(fee+friction); notional=min(equity*.75,equity*.0025*entry/risk_frac)
            qty=notional/entry
            if notional<10: rejections+=1; continue
            stop_px=entry-side*dist
            pos={'asset':asset,'strategy':strategy,'side':side,'signal_ms':t,'entry_ms':h1[i+1]['timestamp_ms'],'entry':entry,'qty':qty,'notional':notional,'stop':stop_px,'risk_dist':dist,'extreme':entry,'trail_active':False,'funding':0.,'funding_missing_hours':0}
        eq_curve.append({'timestamp_ms':t,'equity_usd':equity})
    if pos:
        r=h1[min(stop,n)-1]; px=r['close']*(1-friction*pos['side']); gross=pos['side']*(px-pos['entry'])*pos['qty']; fees=pos['qty']*(pos['entry']+px)*fee; net=gross-fees+pos['funding']; equity+=net; pos.update(exit_ms=r['timestamp_ms'],exit=px,gross=gross,fees=fees,net=net,reason='period_end',equity=equity); trades.append(pos)
    wins=[x['net'] for x in trades if x['net']>0]; losses=[x['net'] for x in trades if x['net']<=0]; pf=sum(wins)/abs(sum(losses)) if losses and sum(losses) else (float('inf') if wins else 0)
    rets=[x['net']/900 for x in trades]; sharpe=(statistics.mean(rets)/statistics.pstdev(rets)*math.sqrt(365) if len(rets)>1 and statistics.pstdev(rets)>0 else 0)
    metrics={'asset':asset,'strategy':strategy,'period':split[2],'stress':stress,'fee_fraction_per_side':fee,'spread_fraction_per_side':spread,'slippage_fraction_per_side':slippage,'initial_equity_usd':900,'final_equity_usd':round(equity,4),'net_return_fraction':round(equity/900-1,6),'trade_count':len(trades),'profit_factor':round(pf,4) if math.isfinite(pf) else 'inf','win_rate':round(len(wins)/len(trades),4) if trades else 0,'max_drawdown_fraction':round(dd,6),'avg_net_trade_usd':round(statistics.mean([x['net'] for x in trades]),4) if trades else 0,'net_pnl_usd':round(equity-900,4),'gross_pnl_usd':round(sum(x['gross'] for x in trades),4),'fees_usd':round(sum(x['fees'] for x in trades),4),'funding_usd':round(sum(x['funding'] for x in trades),4),'funding_coverage_fraction':round(funding_covered/max(1,stop-start),6),'funding_missing_held_hours':sum(x['funding_missing_hours'] for x in trades),'funding_complete':funding_covered==stop-start,'sharpe_trade_annualized_approx':round(sharpe,4),'rejected_below_min_notional':rejections,'holdout_split_indices':[start,stop]}
    return metrics,trades,eq_curve
def main():
    p=argparse.ArgumentParser(); p.add_argument('--assets',nargs='+',default=['BTC','ETH','SOL','XRP']); p.add_argument('--strategies',nargs='+',default=['trend_donchian','momentum_structure','breakout_retest','ema_pullback']); p.add_argument('--output',default='results'); a=p.parse_args()
    out=ROOT/a.output; out.mkdir(parents=True,exist_ok=True); allm=[]; alltr=[]
    # Fixed chronological windows: parameters are preregistered and never fit to these windows.
    periods=[('train',(0,.55,'train')),('validation',(.55,.65,'validation'))]
    for fold,(lo,hi) in enumerate(((.65,.70),(.70,.75),(.75,.80),(.80,.85)),1): periods.append((f'wf_{fold}',(lo,hi,f'wf_{fold}')))
    periods.append(('final_holdout',(.85,1.,'final_holdout')))
    for asset in a.assets:
      for strategy in a.strategies:
       for _,split in periods:
        for stress in (False,True):
         m,tr,eq=run(asset,strategy,split,stress); allm.append(m); alltr.extend([{**x,'stress':stress,'period':split[2]} for x in tr])
    (out/'metrics.json').write_text(json.dumps({'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'results':allm},indent=2),encoding='utf8')
    with (out/'trades.csv').open('w',newline='',encoding='utf8') as f:
      fields=list(dict.fromkeys(k for row in alltr for k in row)); w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(alltr)
    with (out/'metrics.csv').open('w',newline='',encoding='utf8') as f:
      fields=list(allm[0]); w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(allm)
    print(f"Wrote {len(allm)} experiments and {len(alltr)} trade records to {out}")
if __name__=='__main__': main()
