#!/usr/bin/env python3
"""Replay fixed 1h breakout/retest entries with 5m Kraken execution bars."""
from __future__ import annotations
import bisect,csv,datetime as dt,hashlib,json,math,statistics
from pathlib import Path
from .backtest import signals,load
from .portfolio_momentum import ASSETS,INITIAL,FEE,BASE_FRICTION,STRESS_FRICTION,MOMENTUM_LOOKBACK,dt_ms,utc
from .portfolio_concurrency import DAILY_STOP,WEEKLY_STOP,DD_STOP

ROOT=Path(__file__).resolve().parents[1]
WINDOWS=(('train_full','2023-11-02T00:00:00Z','2025-10-30T00:00:00Z'),
         ('wf_1','2025-10-30T00:00:00Z','2026-02-01T00:00:00Z'),
         ('wf_2','2026-02-01T00:00:00Z','2026-05-22T00:00:00Z'),
         ('final_holdout_screened','2026-05-22T00:00:00Z','2026-11-02T00:00:00Z'))
RISK=.0025;NOTIONAL_CAP=.75;HOUR=3_600_000;BAR5=300_000

def bars5(asset):
    p=ROOT/'data'/'raw'/f'kraken_futures_{asset}_5m.csv'
    with p.open(newline='',encoding='utf8') as f:rows=list(csv.DictReader(f))
    for r in rows:
        for k in ('timestamp_ms','open','high','low','close','volume'):r[k]=int(r[k]) if k=='timestamp_ms' else float(r[k])
    return rows

def prep():
    d={}
    for a in ASSETS:
        h1,h4,fund=load(a);_,ats,tr,sig,_=signals(a,'breakout_retest')
        b5=bars5(a);h1ts=[x['timestamp_ms'] for x in h1]
        d[a]={'bars':b5,'bars1h':h1,'h1ts':h1ts,'atr1h':ats,'trend1h':tr,'sig1h':sig,'fund':fund}
    ts=[x['timestamp_ms'] for x in d['BTC']['bars']]
    if any(y-x!=BAR5 for x,y in zip(ts,ts[1:])):raise ValueError('5m BTC series has gaps; inspect manifests before testing')
    for a,m in d.items():
        x=[r['timestamp_ms'] for r in m['bars']]
        if x!=ts:raise ValueError(f'{a} 5m timestamp grid differs from BTC')
    return d

def run(data,start_ms,end_ms,stress=False):
    ts=[r['timestamp_ms'] for r in data['BTC']['bars']];lo=bisect.bisect_left(ts,start_ms);hi=bisect.bisect_left(ts,end_ms)
    friction=STRESS_FRICTION if stress else BASE_FRICTION;eq=INITIAL;peak=INITIAL;dd=0.;pos=None;trades=[];curve=[]
    day0=week0=INITIAL;day_id=week_id=None;last_mark=INITIAL;halt_dd=False;kill_counts={'daily':0,'weekly':0,'drawdown':0};funded=missing=0
    for k in range(lo,hi):
        t=ts[k];day=t//86_400_000;week=(day+3)//7
        # Anchor calendar risk limits to the account's prior marked equity, including
        # any open-position PnL, rather than realized balance alone.
        if day!=day_id:day_id=day;day0=last_mark
        if week!=week_id:week_id=week;week0=last_mark
        bar=data['BTC']['bars'][k];new_entry=False
        # Submit a new signal at the 5m bar open using only the prior completed 1h
        # candle and equity known before this 5m bar's high/low are observed.
        if pos is None and not halt_dd and t%HOUR==0 and k<hi-1 and eq/day0-1>DAILY_STOP and eq/week0-1>WEEKLY_STOP and eq/peak-1>DD_STOP:
            candidates=[]
            for a,m in data.items():
                j=bisect.bisect_left(m['h1ts'],t)-1
                hidx=bisect.bisect_right(m['h1ts'],t)-1
                if j<max(MOMENTUM_LOOKBACK,201) or m['h1ts'][j]+HOUR!=t:continue
                side=m['sig1h'][j]
                if not side or m['trend1h'][j]!=side or m['trend1h'][hidx]!=side or not m['atr1h'][j] or m['atr1h'][j]<=0:continue
                score=side*(m['bars1h'][j]['close']/m['bars1h'][j-MOMENTUM_LOOKBACK]['close']-1)
                if score>0:candidates.append((score,a,side,j))
            if candidates:
                score,a,side,j=max(candidates);m=data[a];dist=2*m['atr1h'][j];raw_open=m['bars'][k]['open'];entry=raw_open*(1+friction*side);stop=entry-side*dist
                viable=(raw_open>stop if side==1 else raw_open<stop)
                if viable:
                    rf=dist/entry+2*(FEE+friction);notional=min(eq*NOTIONAL_CAP,eq*RISK/rf)
                    if notional>=10:
                        pos={'asset':a,'strategy':'breakout_retest_1h_signal_5m_execution','side':side,'momentum_30d':score,'signal_ms':m['h1ts'][j],'entry_ms':t,'entry':entry,'qty':notional/entry,'notional':notional,'stop':stop,'risk_dist':dist,'extreme':entry,'trail_active':False,'funding':0.,'missing_funding_hours':0}
                        new_entry=True
        if pos is not None:
            m=data[pos['asset']];b=m['bars'][k];side=pos['side']
            if t%HOUR==0 and not new_entry:
                rate=m['fund'].get(t)
                if rate is None:pos['missing_funding_hours']+=1;missing+=1
                else:pos['funding']+=-side*rate*pos['qty']*pos['entry'];funded+=1
            hidx=bisect.bisect_right(m['h1ts'],t)-1;atridx=max(0,hidx-1);atr=m['atr1h'][atridx]
            trend=m['trend1h'][hidx]
            hit=b['low']<=pos['stop'] if side==1 else b['high']>=pos['stop'];px=None;reason=''
            if hit:
                px=min(pos['stop'],b['open']) if side==1 else max(pos['stop'],b['open']);reason='stop_5m'
            elif trend==-side:px=b['open'];reason='trend_flip'
            else:
                fav=b['high']-pos['entry'] if side==1 else pos['entry']-b['low']
                if fav>=pos['risk_dist']:pos['trail_active']=True
                if pos['trail_active'] and atr:
                    cand=pos['extreme']-3*atr if side==1 else pos['extreme']+3*atr
                    pos['stop']=max(pos['stop'],cand) if side==1 else min(pos['stop'],cand)
                pos['extreme']=max(pos['extreme'],b['high']) if side==1 else min(pos['extreme'],b['low'])
            if px is None and k==hi-1:px=b['close'];reason='period_end'
            if px is not None:
                out=px*(1-friction*side);gross=side*(out-pos['entry'])*pos['qty'];fees=pos['qty']*(pos['entry']+out)*FEE;net=gross-fees+pos['funding'];eq+=net
                pos.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason=reason,equity=eq);trades.append(pos);pos=None
        # Conservative adverse 5m mark; no mark-price feed is available.
        mark=eq
        if pos is not None:
            m=data[pos['asset']];b=m['bars'][k];adverse=b['low'] if pos['side']==1 else b['high']
            mark+=pos['side']*(adverse-pos['entry'])*pos['qty']-pos['qty']*(pos['entry']+adverse)*FEE+pos['funding']
        peak=max(peak,mark);dd=min(dd,mark/peak-1);kill=None
        if mark/peak-1<=DD_STOP:
            halt_dd=True
            if pos is not None:kill='portfolio_dd_kill_switch';kill_counts['drawdown']+=1
        elif pos is not None and mark/day0-1<=DAILY_STOP:kill='daily_loss_kill_switch';kill_counts['daily']+=1
        elif pos is not None and mark/week0-1<=WEEKLY_STOP:kill='weekly_loss_kill_switch';kill_counts['weekly']+=1
        if kill:
            p=pos;b=data[p['asset']]['bars'][k];adverse=b['low'] if p['side']==1 else b['high'];side=p['side'];out=adverse*(1-friction*side)
            gross=side*(out-p['entry'])*p['qty'];fees=p['qty']*(p['entry']+out)*FEE;net=gross-fees+p['funding'];eq+=net
            p.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason=kill,equity=eq);trades.append(p);pos=None;mark=eq;peak=max(peak,mark);dd=min(dd,mark/peak-1)
        if t%HOUR==0 or k==hi-1:
            risk_usd=(max(0,pos['side']*(pos['entry']-pos['stop'])*pos['qty'])+pos['notional']*2*(FEE+friction)) if pos else 0.
            curve.append({'timestamp_ms':t,'equity_usd':round(eq,6),'adverse_mark_equity_usd':round(mark,6),'open_positions':int(pos is not None),'open_stop_risk_usd':round(risk_usd,6)})
        last_mark=mark
    if pos:
        p=pos;b=data[p['asset']]['bars'][hi-1];side=p['side'];out=b['close']*(1-friction*side);gross=side*(out-p['entry'])*p['qty'];fees=p['qty']*(p['entry']+out)*FEE;net=gross-fees+p['funding'];eq+=net;p.update(exit_ms=ts[hi-1],exit=out,gross=gross,fees=fees,net=net,reason='period_end',equity=eq);trades.append(p)
        peak=max(peak,eq);dd=min(dd,eq/peak-1);curve.append({'timestamp_ms':ts[hi-1],'equity_usd':round(eq,6),'adverse_mark_equity_usd':round(eq,6),'open_positions':0,'open_stop_risk_usd':0.})
    wins=[x['net'] for x in trades if x['net']>0];loss=[x['net'] for x in trades if x['net']<=0];pf=sum(wins)/abs(sum(loss)) if loss and sum(loss) else ('inf' if wins else 0)
    marks=[x['adverse_mark_equity_usd'] for x in curve];rets=[marks[j]/marks[j-1]-1 for j in range(1,len(marks)) if marks[j-1]>0];sd=statistics.pstdev(rets) if len(rets)>1 else 0;sh=statistics.mean(rets)/sd*math.sqrt(24*365) if sd else 0
    metric={'stress':stress,'window_start_utc':utc(ts[lo]),'window_end_utc':utc(ts[hi-1]),'initial_equity_usd':INITIAL,'final_equity_usd':round(eq,4),'net_pnl_usd':round(eq-INITIAL,4),'net_return_fraction':round(eq/INITIAL-1,6),'trade_count':len(trades),'expectancy_per_trade_usd':round(statistics.mean([x['net'] for x in trades]),6) if trades else 0,'profit_factor':round(pf,4) if isinstance(pf,float) else pf,'win_rate':round(len(wins)/len(trades),4) if trades else 0,'max_drawdown_fraction':round(dd,6),'fees_usd':round(sum(x['fees'] for x in trades),4),'funding_usd':round(sum(x['funding'] for x in trades),4),'funding_coverage_fraction':round(funded/max(1,funded+missing),6),'funding_missing_held_hours':missing,'max_observed_concurrent_positions':max((x['open_positions'] for x in curve),default=0),'max_open_stop_risk_fraction':round(max((x['open_stop_risk_usd'] for x in curve),default=0)/INITIAL,6),'sharpe_hourly_annualized_approx':round(sh,4),'kill_switch_triggers':kill_counts,'risk_limits':{'daily':DAILY_STOP,'weekly':WEEKLY_STOP,'drawdown':DD_STOP}}
    return metric,trades,curve

def main():
    data=prep();results=[];alltr=[];allcurve=[]
    for window,start,end in WINDOWS:
      for stress in (False,True):
        m,tr,eq=run(data,dt_ms(start),dt_ms(end),stress);m['window']=window;results.append(m)
        alltr += [{**x,'window':window,'stress':stress} for x in tr];allcurve += [{**x,'window':window,'stress':stress} for x in eq]
        print(window,'stress' if stress else 'base','return',m['net_return_fraction'],'PF',m['profit_factor'],'DD',m['max_drawdown_fraction'],'n',m['trade_count'])
    out=ROOT/'results'/'intrabar_execution_screen';out.mkdir(exist_ok=True,parents=True)
    files=sorted((ROOT/'data'/'raw').glob('*_1h.csv'))+sorted((ROOT/'data'/'raw').glob('*_5m.csv'))+sorted((ROOT/'data'/'processed').glob('*_funding_complete_1h.csv'))
    doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'signal_code_sha256':hashlib.sha256((ROOT/'src'/'backtest.py').read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'method':'1h closed-bar signals, order at next 5m open; 1h ATR stops/trails updated against every 5m trade candle; stop-first same-bar ambiguity; gap-through stop fills at 5m open; 5m adverse mark; fixed total 0.25% stop risk; 1 position; Kraken hourly funding; 5m OHLC is trade-price data, not mark-price or queue data','risk_budget_fraction_total':RISK,'results':results}
    (out/'metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for name,rows in [('trades.csv',alltr),('equity.csv',allcurve)]:
        with (out/name).open('w',newline='',encoding='utf8') as f:
            fields=list(dict.fromkeys(k for row in rows for k in row));w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(rows)
    with (out/'metrics_summary.csv').open('w',newline='',encoding='utf8') as f:
        fields=list(results[0]);w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(results)
if __name__=='__main__':main()
