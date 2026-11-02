#!/usr/bin/env python3
"""Concurrency/risk screen for the fixed breakout-retest candidate. Research only."""
from __future__ import annotations
import csv,datetime as dt,hashlib,json,math,statistics
from pathlib import Path
from .backtest import signals
from .portfolio_momentum import ASSETS,MOMENTUM_LOOKBACK,INITIAL,FEE,BASE_FRICTION,STRESS_FRICTION,dt_ms,utc
ROOT=Path(__file__).resolve().parents[1]
STRATEGY='breakout_retest'
WINDOWS=(('funding_era','2025-10-30T00:00:00Z','2026-11-02T00:00:00Z'),('wf_1','2025-10-30T00:00:00Z','2026-02-01T00:00:00Z'),('wf_2','2026-02-01T00:00:00Z','2026-05-22T00:00:00Z'),('final_holdout_screened','2026-05-22T00:00:00Z','2026-11-02T00:00:00Z'))
# name, slots, stop-risk budget/trade, notional cap/trade. Capital-allocation
# cases use 3-4% margin at max 2x leverage (=6-8% notional per position).
CONFIGS=(('1pos_0.25pct',1,.0025,.75),('2pos_0.25pct',2,.0025,.75),
         ('3pos_0.25pct',3,.0025,.75),('4pos_0.25pct',4,.0025,.75))
DAILY_STOP=-.01; WEEKLY_STOP=-.03; DD_STOP=-.06; NOTIONAL_CAP=.75

def prep():
    d={}
    for a in ASSETS:
        h,atr,tr,sig,fu=signals(a,STRATEGY);d[a]={'bars':h,'atr':atr,'trend':tr,'sig':sig,'fund':fu}
    return d

def run(data,start_ms,end_ms,slots,risk,notional_cap,stress=False):
    ts=[x['timestamp_ms'] for x in data['BTC']['bars']];lo=next(i for i,t in enumerate(ts) if t>=start_ms);hi=next((i for i,t in enumerate(ts) if t>=end_ms),len(ts))
    friction=STRESS_FRICTION if stress else BASE_FRICTION;eq=INITIAL;peak=INITIAL;dd=0.;pos=[];trades=[];curve=[];funded=missing=0;day0=week0=INITIAL;day_id=week_id=None;drawdown_halt=False;daily_triggers=weekly_triggers=dd_triggers=0
    for i in range(max(lo,MOMENTUM_LOOKBACK+1,201),min(hi,len(ts)-1)):
        t=ts[i];day=t//86400000;week=(day+3)//7  # UTC Monday-based week; Unix epoch began Thursday.
        if day!=day_id:day_id=day;day0=eq
        if week!=week_id:week_id=week;week0=eq
        active=[]
        for p in pos:
            m=data[p['asset']];b=m['bars'][i];atr=m['atr'][i];rate=m['fund'].get(t)
            if rate is None:p['missing_funding']+=1;missing+=1
            else:p['funding']+=-p['side']*rate*p['qty']*p['entry'];funded+=1
            hit=b['low']<=p['stop'] if p['side']==1 else b['high']>=p['stop'];flip=m['trend'][i]==-p['side'];px=None;reason=''
            if hit:px=p['stop'];reason='stop'
            elif flip:px=b['open'];reason='trend_flip'
            else:
                fav=b['high']-p['entry'] if p['side']==1 else p['entry']-b['low']
                if fav>=p['risk_dist']:p['trail_active']=True
                if p['trail_active'] and atr:
                    cand=p['extreme']-3*atr if p['side']==1 else p['extreme']+3*atr
                    p['stop']=max(p['stop'],cand) if p['side']==1 else min(p['stop'],cand)
                p['extreme']=max(p['extreme'],b['high']) if p['side']==1 else min(p['extreme'],b['low'])
                if i==hi-1:px=b['close'];reason='period_end'
            if px is None:active.append(p)
            else:
                out=px*(1-friction*p['side']);gross=p['side']*(out-p['entry'])*p['qty'];fees=p['qty']*(p['entry']+out)*FEE;net=gross-fees+p['funding'];eq+=net
                p.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason=reason,equity=eq);trades.append(p)
        pos=active
        mark=eq
        for p in pos:
            b=data[p['asset']]['bars'][i];adverse=b['low'] if p['side']==1 else b['high']
            mark+=p['side']*(adverse-p['entry'])*p['qty']-p['qty']*(p['entry']+adverse)*FEE+p['funding']
        peak=max(peak,mark);dd=min(dd,mark/peak-1)
        kill_reason=None
        if mark/peak-1<=DD_STOP:
            drawdown_halt=True
            if pos:kill_reason='portfolio_dd_kill_switch';dd_triggers+=1
        elif pos and mark/day0-1<=DAILY_STOP:
            kill_reason='daily_loss_kill_switch';daily_triggers+=1
        elif pos and mark/week0-1<=WEEKLY_STOP:
            kill_reason='weekly_loss_kill_switch';weekly_triggers+=1
        if kill_reason:
            # Liquidate at the adverse bar extreme plus modeled slippage. The realized
            # loss may exceed a threshold because OHLC bars cannot model intrabar timing.
            for p in pos:
                b=data[p['asset']]['bars'][i];px=b['low'] if p['side']==1 else b['high']
                out=px*(1-friction*p['side']);gross=p['side']*(out-p['entry'])*p['qty'];fees=p['qty']*(p['entry']+out)*FEE;net=gross-fees+p['funding'];eq+=net
                p.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason=kill_reason,equity=eq);trades.append(p)
            pos=[];mark=eq;peak=max(peak,mark);dd=min(dd,mark/peak-1)
        if i<hi-1 and not drawdown_halt and len(pos)<slots and mark/day0-1>DAILY_STOP and mark/week0-1>WEEKLY_STOP and mark/peak-1>DD_STOP:
            held={p['asset'] for p in pos};cands=[]
            for a,m in data.items():
                if a in held:continue
                side=m['sig'][i]
                if not side or m['trend'][i]!=side or not m['atr'][i] or m['atr'][i]<=0:continue
                score=side*(m['bars'][i]['close']/m['bars'][i-MOMENTUM_LOOKBACK]['close']-1)
                if score>0:cands.append((score,a,side))
            for score,a,side in sorted(cands,reverse=True):
                if len(pos)>=slots:break
                m=data[a];dist=2*m['atr'][i];entry=m['bars'][i+1]['open']*(1+friction*side);rf=dist/entry+2*(FEE+friction)
                notional=min(eq*notional_cap,eq*NOTIONAL_CAP,eq*risk/rf)
                if notional<10:continue
                pos.append({'asset':a,'strategy':STRATEGY,'side':side,'momentum_30d':score,'signal_ms':t,'entry_ms':ts[i+1],'entry':entry,'qty':notional/entry,'notional':notional,'stop':entry-side*dist,'risk_dist':dist,'initial_stop_risk_usd':notional*rf,'extreme':entry,'trail_active':False,'funding':0.,'missing_funding':0});held.add(a)
        risk_usd=sum(max(0,p['side']*(p['entry']-p['stop'])*p['qty'])+p['notional']*2*(FEE+friction) for p in pos)
        curve.append({'timestamp_ms':t,'equity_usd':round(eq,6),'adverse_mark_equity_usd':round(mark,6),'open_positions':len(pos),'open_stop_risk_usd':round(risk_usd,6),'open_notional_usd':round(sum(p['notional'] for p in pos),6)})
    if pos:
        t=ts[min(max(hi-1,0),len(ts)-1)]
        for p in pos:
            b=data[p['asset']]['bars'][min(hi,len(ts))-1];out=b['close']*(1-friction*p['side']);gross=p['side']*(out-p['entry'])*p['qty'];fees=p['qty']*(p['entry']+out)*FEE;net=gross-fees+p['funding'];eq+=net;p.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason='period_end',equity=eq);trades.append(p)
    if curve:
        peak=max(peak,eq);dd=min(dd,eq/peak-1)
        curve.append({'timestamp_ms':ts[min(max(hi-1,0),len(ts)-1)],'equity_usd':round(eq,6),'adverse_mark_equity_usd':round(eq,6),'open_positions':0,'open_stop_risk_usd':0.,'open_notional_usd':0.})
    wins=[p['net'] for p in trades if p['net']>0];loss=[p['net'] for p in trades if p['net']<=0];pf=sum(wins)/abs(sum(loss)) if loss and sum(loss) else ('inf' if wins else 0)
    marks=[x['adverse_mark_equity_usd'] for x in curve];rets=[marks[j]/marks[j-1]-1 for j in range(1,len(marks)) if marks[j-1]>0];sd=statistics.pstdev(rets) if len(rets)>1 else 0;sh=statistics.mean(rets)/sd*math.sqrt(24*365) if sd else 0
    return {'start_utc':utc(ts[lo]),'end_utc':utc(ts[min(hi,len(ts)-1)]),'stress':stress,'max_concurrent_positions':slots,'risk_per_trade_fraction':risk,'max_stop_risk_fraction_if_full':round(slots*risk,6),'max_notional_fraction_per_position':notional_cap,'initial_equity_usd':INITIAL,'final_equity_usd':round(eq,4),'net_return_fraction':round(eq/INITIAL-1,6),'net_pnl_usd':round(eq-INITIAL,4),'trade_count':len(trades),'profit_factor':round(pf,4) if isinstance(pf,float) else pf,'win_rate':round(len(wins)/len(trades),4) if trades else 0,'max_drawdown_fraction':round(dd,6),'fees_usd':round(sum(p['fees'] for p in trades),4),'funding_usd':round(sum(p['funding'] for p in trades),4),'funding_coverage_fraction':round(funded/max(funded+missing,1),6),'funding_missing_held_hours':missing,'max_observed_concurrent_positions':max((x['open_positions'] for x in curve),default=0),'max_open_notional_multiple':round(max((x['open_notional_usd'] for x in curve),default=0)/INITIAL,4),'sharpe_hourly_annualized_approx':round(sh,4),'risk_controls':{'daily_hard_liquidation':DAILY_STOP,'weekly_hard_liquidation':WEEKLY_STOP,'drawdown_hard_liquidation_and_permanent_halt':DD_STOP,'daily_liquidation_triggers':daily_triggers,'weekly_liquidation_triggers':weekly_triggers,'drawdown_liquidation_triggers':dd_triggers,'one_position_per_asset':True,'notional_cap_per_position':NOTIONAL_CAP}},trades,curve

def main():
    data=prep();metrics=[];trades=[];curves=[]
    for label,slots,risk,notional_cap in CONFIGS:
      for win,a,b in WINDOWS:
       for stress in (False,True):
        m,tr,eq=run(data,dt_ms(a),dt_ms(b),slots,risk,notional_cap,stress);m.update(config=label,window=win);metrics.append(m);trades += [{**x,'config':label,'window':win,'stress':stress} for x in tr];curves += [{**x,'config':label,'window':win,'stress':stress} for x in eq]
    out=ROOT/'results';out.mkdir(exist_ok=True)
    doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'strategy':STRATEGY,'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'signal_code_sha256':hashlib.sha256((ROOT/'src'/'backtest.py').read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'data'/'raw').glob('*_1h.csv'))},'results':metrics}
    (out/'portfolio_concurrency_metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for fname,rows in [('portfolio_concurrency_trades.csv',trades),('portfolio_concurrency_equity.csv',curves)]:
        with (out/fname).open('w',newline='',encoding='utf8') as f:
            fields=list(dict.fromkeys(k for row in rows for k in row));w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    for x in metrics:
        if x['window']=='funding_era':print(x['config'],'stress' if x['stress'] else 'base',x['net_return_fraction'],'PF',x['profit_factor'],'DD',x['max_drawdown_fraction'],'trades',x['trade_count'],'maxpos',x['max_observed_concurrent_positions'])
if __name__=='__main__':main()
