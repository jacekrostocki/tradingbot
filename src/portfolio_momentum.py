#!/usr/bin/env python3
"""Conservative one-position cross-asset momentum/structure research test.
No exchange execution code. Signals are evaluated at closed hourly bars; entries occur next open.
"""
from __future__ import annotations
import csv, datetime as dt, hashlib, json, math, statistics
from pathlib import Path
try:  # Support both `python -m src.portfolio_momentum` and direct script execution.
    from .backtest import signals
except ImportError:
    from backtest import signals

ROOT=Path(__file__).resolve().parents[1]
ASSETS=('BTC','ETH','SOL','XRP')
STRATEGIES=('trend_donchian','momentum_structure','breakout_retest','ema_pullback')
INITIAL=900.0
FEE=.0005
BASE_FRICTION=.00030  # 1.5 bps spread + 1.5 bps slippage, per side
STRESS_FRICTION=.00075 # 3.75 bps spread + 3.75 bps slippage, per side
RISK=.0025
NOTIONAL_CAP=.75
MOMENTUM_LOOKBACK=24*30


def dt_ms(s): return int(dt.datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()*1000)
def utc(ms): return dt.datetime.fromtimestamp(ms/1000,dt.timezone.utc).isoformat()

def run(start_ms, end_ms, stress=False, strategy=STRATEGIES[0]):
    market={}
    for asset in ASSETS:
        h1, atrs, trend, sig, funding=signals(asset,strategy)
        market[asset]={'bars':h1,'atr':atrs,'trend':trend,'sig':sig,'funding':funding,
                       'bytime':{r['timestamp_ms']:i for i,r in enumerate(h1)}}
    times=[r['timestamp_ms'] for r in market['BTC']['bars']]
    start=next(i for i,t in enumerate(times) if t>=start_ms)
    stop=next((i for i,t in enumerate(times) if t>=end_ms),len(times))
    friction=STRESS_FRICTION if stress else BASE_FRICTION
    equity=INITIAL; peak=INITIAL; maxdd=0.; pos=None; trades=[]; curve=[]; missing=0; covered=0; heldhours=0
    day_start=week_start=INITIAL; day_id=week_id=None
    for i in range(max(start,MOMENTUM_LOOKBACK+1,201), min(stop,len(times)-1)):
        t=times[i]; day=t//86400000; week=t//(7*86400000)
        if day!=day_id: day_id=day; day_start=equity
        if week!=week_id: week_id=week; week_start=equity
        # Close/update an open position using only this bar's known OHLCV.
        if pos:
            b=market[pos['asset']]['bars'][i]; atr=market[pos['asset']]['atr'][i]; f=market[pos['asset']]['funding']
            rate=f.get(t)
            if rate is None: missing+=1; pos['missing_funding']+=1
            else:
                pos['funding'] += -pos['side']*rate*pos['qty']*pos['entry']; covered+=1
            heldhours+=1
            stop_hit=(b['low']<=pos['stop'] if pos['side']==1 else b['high']>=pos['stop'])
            reverse=market[pos['asset']]['trend'][i]==-pos['side']
            exit_px=None; reason=''
            if stop_hit: exit_px=pos['stop']; reason='stop'
            elif reverse: exit_px=b['open']; reason='trend_flip'
            else:
                fav=(b['high']-pos['entry'] if pos['side']==1 else pos['entry']-b['low'])
                if fav>=pos['risk_dist']: pos['trail_active']=True
                if pos['trail_active'] and atr:
                    candidate=(pos['extreme']-3*atr if pos['side']==1 else pos['extreme']+3*atr)
                    pos['stop']=max(pos['stop'],candidate) if pos['side']==1 else min(pos['stop'],candidate)
                pos['extreme']=max(pos['extreme'],b['high']) if pos['side']==1 else min(pos['extreme'],b['low'])
                if i==stop-1: exit_px=b['close']; reason='period_end'
            if exit_px is not None:
                px=exit_px*(1-friction*pos['side'])
                gross=pos['side']*(px-pos['entry'])*pos['qty']
                fees=pos['qty']*(pos['entry']+px)*FEE
                net=gross-fees+pos['funding']; equity+=net
                pos.update(exit_ms=t,exit=px,gross=gross,fees=fees,net=net,reason=reason,equity=equity)
                trades.append(pos); pos=None
        # Adverse intrabar mark used for drawdown; do not count funding twice.
        mark=equity
        if pos:
            b=market[pos['asset']]['bars'][i]; adverse=b['low'] if pos['side']==1 else b['high']
            mark+=pos['side']*(adverse-pos['entry'])*pos['qty']-pos['qty']*(pos['entry']+adverse)*FEE
        peak=max(peak,mark); maxdd=min(maxdd,mark/peak-1)
        # One global position. The eligible asset with the strongest sign-aligned 30d return wins.
        if pos is None and i<stop-1 and (mark/day_start-1)>-.01 and (mark/week_start-1)>-.03 and (mark/peak-1)>-.06:
            candidates=[]
            for asset,m in market.items():
                b=m['bars'][i]; side=m['sig'][i]
                if not side or m['trend'][i]!=side: continue
                past=m['bars'][i-MOMENTUM_LOOKBACK]['close']
                score=side*(b['close']/past-1)
                if score>0 and m['atr'][i] and m['atr'][i]>0: candidates.append((score,asset,side))
            if candidates:
                score,asset,side=max(candidates)
                m=market[asset]; b=m['bars'][i]; atr=m['atr'][i]
                next_open=m['bars'][i+1]['open']; entry=next_open*(1+friction*side); dist=2*atr
                risk_dist_frac=dist/entry+2*(FEE+friction)
                notional=min(equity*NOTIONAL_CAP,equity*RISK/risk_dist_frac)
                if notional>=10:
                    qty=notional/entry
                pos={'asset':asset,'strategy':strategy,'side':side,'momentum_30d':score,
                         'signal_ms':t,'entry_ms':times[i+1],'entry':entry,'qty':qty,'notional':notional,
                         'stop':entry-side*dist,'risk_dist':dist,'extreme':entry,'trail_active':False,
                         'funding':0.,'missing_funding':0}
        curve.append({'timestamp_ms':t,'equity_usd':round(equity,6),'mark_equity_usd':round(mark,6)})
    if pos:
        b=market[pos['asset']]['bars'][min(stop,len(times))-1]; t=b['timestamp_ms']
        px=b['close']*(1-friction*pos['side']); gross=pos['side']*(px-pos['entry'])*pos['qty']; fees=pos['qty']*(pos['entry']+px)*FEE
        net=gross-fees+pos['funding']; equity+=net
        pos.update(exit_ms=t,exit=px,gross=gross,fees=fees,net=net,reason='period_end',equity=equity); trades.append(pos)
    wins=[x['net'] for x in trades if x['net']>0]; losses=[x['net'] for x in trades if x['net']<=0]
    pf=sum(wins)/abs(sum(losses)) if losses and sum(losses) else ('inf' if wins else 0)
    # Approximate annualized Sharpe from hourly equity changes, useful only as descriptive statistic.
    marks=[x['mark_equity_usd'] for x in curve]
    rets=[marks[j]/marks[j-1]-1 for j in range(1,len(marks)) if marks[j-1]>0]
    sd=statistics.pstdev(rets) if len(rets)>1 else 0
    sharpe=statistics.mean(rets)/sd*math.sqrt(24*365) if sd else 0
    return {'period_start_utc':utc(times[start]),'period_end_utc':utc(times[min(stop,len(times)-1)]),
            'stress':stress,'initial_equity_usd':INITIAL,'final_equity_usd':round(equity,4),
            'net_return_fraction':round(equity/INITIAL-1,6),'net_pnl_usd':round(equity-INITIAL,4),
            'trade_count':len(trades),'profit_factor':round(pf,4) if isinstance(pf,float) else pf,
            'win_rate':round(len(wins)/len(trades),4) if trades else 0,
            'max_drawdown_fraction':round(maxdd,6),'fees_usd':round(sum(x['fees'] for x in trades),4),
            'funding_usd':round(sum(x['funding'] for x in trades),4),'funding_observed_held_hours':covered,
            'funding_missing_held_hours':missing,'funding_coverage_fraction':round(covered/max(covered+missing,1),6),
            'sharpe_hourly_annualized_approx':round(sharpe,4),'strategy':strategy,'parameters':{'risk_per_trade':RISK,'max_notional_multiple':NOTIONAL_CAP,
            'fee_per_side':FEE,'spread_plus_slippage_per_side':friction,'momentum_lookback_hours':MOMENTUM_LOOKBACK,'max_positions_total':1}},trades,curve

def main():
    start=dt_ms('2025-10-30T00:00:00Z'); end=dt_ms('2026-11-02T00:00:00Z')
    # Funding-era chronological folds: fixed rules, no parameter tuning.
    boundaries=[start,dt_ms('2026-02-01T00:00:00Z'),dt_ms('2026-05-22T00:00:00Z'),end]
    windows=[('funding_era',boundaries[0],boundaries[3]),('wf_1',boundaries[0],boundaries[1]),
             ('wf_2',boundaries[1],boundaries[2]),('final_holdout_screened',boundaries[2],boundaries[3])]
    out=ROOT/'results'; out.mkdir(exist_ok=True)
    allm=[]; alltr=[]; allcurves=[]
    for strategy in STRATEGIES:
      for name,lo,hi in windows:
        for stress in (False,True):
            m,tr,curve=run(lo,hi,stress,strategy); m['window']=name; allm.append(m)
            alltr.extend([{**x,'window':name,'stress':stress} for x in tr])
            allcurves.extend([{**x,'window':name,'stress':stress} for x in curve])
    doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
         'source_strategy_code_sha256':hashlib.sha256((ROOT/'src'/'backtest.py').read_bytes()).hexdigest(),
         'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'data'/'raw').glob('*_1h.csv')) if not p.name.endswith('.manifest.json')},
         'results':allm}
    (out/'portfolio_momentum_metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for name,rows in [('portfolio_momentum_trades.csv',alltr),('portfolio_momentum_equity.csv',allcurves)]:
        with (out/name).open('w',newline='',encoding='utf8') as f:
            fields=list(dict.fromkeys(k for row in rows for k in row)); w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    print(json.dumps(allm,indent=2))
if __name__=='__main__': main()
