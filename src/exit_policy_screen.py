#!/usr/bin/env python3
"""Predeclared exit-policy comparison for the Kraken breakout/retest portfolio.
Research only: fixed entry signal, fixed 0.25% portfolio risk, one open position.
"""
from __future__ import annotations
import csv,datetime as dt,hashlib,json,math,statistics
from pathlib import Path
from .portfolio_concurrency import prep,DAILY_STOP,WEEKLY_STOP,DD_STOP
from .portfolio_momentum import INITIAL,FEE,BASE_FRICTION,STRESS_FRICTION,MOMENTUM_LOOKBACK,dt_ms,utc

ROOT=Path(__file__).resolve().parents[1]
WINDOWS=(('train_full','2023-11-02T00:00:00Z','2025-10-30T00:00:00Z'),
         ('wf_1','2025-10-30T00:00:00Z','2026-02-01T00:00:00Z'),
         ('wf_2','2026-02-01T00:00:00Z','2026-05-22T00:00:00Z'),
         ('final_holdout_screened','2026-05-22T00:00:00Z','2026-11-02T00:00:00Z'))
VARIANTS=(('trail_3atr_after_1r',None,None),('fixed_tp_1_5r',1.5,None),
          ('fixed_tp_2r',2.,None),('trail_plus_72h_time_stop',None,72))
RISK=.0025;NOTIONAL_CAP=.75;SLOTS=1

def run(data,start_ms,end_ms,variant,target_r,max_hours,stress=False):
    ts=[r['timestamp_ms'] for r in data['BTC']['bars']]
    lo=next(i for i,t in enumerate(ts) if t>=start_ms);hi=next((i for i,t in enumerate(ts) if t>=end_ms),len(ts))
    friction=STRESS_FRICTION if stress else BASE_FRICTION
    eq=INITIAL;peak=INITIAL;dd=0.;pos=None;trades=[];curve=[];day0=week0=INITIAL;day_id=week_id=None
    halt_dd=False;kill_counts={'daily':0,'weekly':0,'drawdown':0}
    for i in range(max(lo,MOMENTUM_LOOKBACK+1,201),min(hi,len(ts)-1)):
        t=ts[i];day=t//86_400_000;week=(day+3)//7
        if day!=day_id:day_id=day;day0=eq
        if week!=week_id:week_id=week;week0=eq
        if pos is not None:
            m=data[pos['asset']];b=m['bars'][i];atr=m['atr'][i];rate=m['fund'].get(t)
            if rate is not None:pos['funding']+=-pos['side']*rate*pos['qty']*pos['entry']
            else:pos['missing_funding_hours']+=1
            side=pos['side'];stop_hit=(b['low']<=pos['stop'] if side==1 else b['high']>=pos['stop'])
            px=None;reason=''
            if stop_hit:
                px=pos['stop'];reason='stop'
            elif target_r is not None:
                target=pos['entry']+side*pos['risk_dist']*target_r
                target_hit=(b['high']>=target if side==1 else b['low']<=target)
                if target_hit:px=target;reason=f'take_profit_{target_r:g}r'
            if px is None and m['trend'][i]==-side:px=b['open'];reason='trend_flip'
            if px is None and max_hours is not None and t-pos['entry_ms']>=max_hours*3_600_000:px=b['close'];reason=f'time_stop_{max_hours}h'
            if px is None and target_r is None:
                fav=b['high']-pos['entry'] if side==1 else pos['entry']-b['low']
                if fav>=pos['risk_dist']:pos['trail_active']=True
                if pos['trail_active'] and atr:
                    cand=pos['extreme']-3*atr if side==1 else pos['extreme']+3*atr
                    pos['stop']=max(pos['stop'],cand) if side==1 else min(pos['stop'],cand)
            pos['extreme']=max(pos['extreme'],b['high']) if side==1 else min(pos['extreme'],b['low'])
            if px is None and i==hi-1:px=b['close'];reason='period_end'
            if px is not None:
                out=px*(1-friction*side);gross=side*(out-pos['entry'])*pos['qty'];fees=pos['qty']*(pos['entry']+out)*FEE;net=gross-fees+pos['funding'];eq+=net
                pos.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason=reason,equity=eq);trades.append(pos);pos=None
        mark=eq
        if pos is not None:
            b=data[pos['asset']]['bars'][i];adverse=b['low'] if pos['side']==1 else b['high']
            mark+=pos['side']*(adverse-pos['entry'])*pos['qty']-pos['qty']*(pos['entry']+adverse)*FEE+pos['funding']
        peak=max(peak,mark);dd=min(dd,mark/peak-1)
        kill=None
        if mark/peak-1<=DD_STOP:
            halt_dd=True
            if pos is not None:kill='portfolio_dd_kill_switch';kill_counts['drawdown']+=1
        elif pos is not None and mark/day0-1<=DAILY_STOP:kill='daily_loss_kill_switch';kill_counts['daily']+=1
        elif pos is not None and mark/week0-1<=WEEKLY_STOP:kill='weekly_loss_kill_switch';kill_counts['weekly']+=1
        if kill:
            p=pos;b=data[p['asset']]['bars'][i];adverse=b['low'] if p['side']==1 else b['high'];side=p['side']
            out=adverse*(1-friction*side);gross=side*(out-p['entry'])*p['qty'];fees=p['qty']*(p['entry']+out)*FEE;net=gross-fees+p['funding'];eq+=net
            p.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason=kill,equity=eq);trades.append(p);pos=None;mark=eq;peak=max(peak,mark);dd=min(dd,mark/peak-1)
        if pos is None and i<hi-1 and not halt_dd and mark/day0-1>DAILY_STOP and mark/week0-1>WEEKLY_STOP and mark/peak-1>DD_STOP:
            cand=[]
            for a,m in data.items():
                side=m['sig'][i]
                if not side or m['trend'][i]!=side or not m['atr'][i] or m['atr'][i]<=0:continue
                momentum=side*(m['bars'][i]['close']/m['bars'][i-MOMENTUM_LOOKBACK]['close']-1)
                if momentum>0:cand.append((momentum,a,side))
            if cand:
                score,a,side=max(cand);m=data[a];dist=2*m['atr'][i];entry=m['bars'][i+1]['open']*(1+friction*side);risk_frac=dist/entry+2*(FEE+friction)
                notional=min(eq*NOTIONAL_CAP,eq*RISK/risk_frac)
                if notional>=10:
                    pos={'asset':a,'strategy':'breakout_retest','variant':variant,'side':side,'momentum_30d':score,'signal_ms':t,'entry_ms':ts[i+1],'entry':entry,'qty':notional/entry,'notional':notional,'stop':entry-side*dist,'risk_dist':dist,'extreme':entry,'trail_active':False,'funding':0.,'missing_funding_hours':0}
        curve.append({'timestamp_ms':t,'equity_usd':round(eq,6),'adverse_mark_equity_usd':round(mark,6),'open_positions':int(pos is not None)})
    if pos is not None:
        t=ts[min(max(hi-1,0),len(ts)-1)];b=data[pos['asset']]['bars'][min(hi,len(ts))-1];side=pos['side'];out=b['close']*(1-friction*side);gross=side*(out-pos['entry'])*pos['qty'];fees=pos['qty']*(pos['entry']+out)*FEE;net=gross-fees+pos['funding'];eq+=net;pos.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason='period_end',equity=eq);trades.append(pos)
    if curve:
        peak=max(peak,eq);dd=min(dd,eq/peak-1);curve.append({'timestamp_ms':ts[min(max(hi-1,0),len(ts)-1)],'equity_usd':round(eq,6),'adverse_mark_equity_usd':round(eq,6),'open_positions':0})
    wins=[x['net'] for x in trades if x['net']>0];loss=[x['net'] for x in trades if x['net']<=0];pf=sum(wins)/abs(sum(loss)) if loss and sum(loss) else ('inf' if wins else 0)
    marks=[x['adverse_mark_equity_usd'] for x in curve];rets=[marks[j]/marks[j-1]-1 for j in range(1,len(marks)) if marks[j-1]>0];sd=statistics.pstdev(rets) if len(rets)>1 else 0;sh=statistics.mean(rets)/sd*math.sqrt(24*365) if sd else 0
    metric={'variant':variant,'window_start_utc':utc(ts[lo]),'window_end_utc':utc(ts[min(hi,len(ts)-1)]),'stress':stress,'slots':SLOTS,'portfolio_risk_budget_fraction':RISK,'initial_equity_usd':INITIAL,'final_equity_usd':round(eq,4),'net_pnl_usd':round(eq-INITIAL,4),'net_return_fraction':round(eq/INITIAL-1,6),'trade_count':len(trades),'expectancy_per_trade_usd':round(statistics.mean([x['net'] for x in trades]),6) if trades else 0,'profit_factor':round(pf,4) if isinstance(pf,float) else pf,'win_rate':round(len(wins)/len(trades),4) if trades else 0,'max_drawdown_fraction':round(dd,6),'fees_usd':round(sum(x['fees'] for x in trades),4),'funding_usd':round(sum(x['funding'] for x in trades),4),'sharpe_hourly_annualized_approx':round(sh,4),'kill_switch_triggers':kill_counts,'risk_limits':{'daily':DAILY_STOP,'weekly':WEEKLY_STOP,'peak_drawdown':DD_STOP}}
    return metric,trades,curve

def main():
    data=prep();results=[];all_trades=[];all_curve=[]
    for variant,target,hours in VARIANTS:
      for window,start,end in WINDOWS:
       for stress in (False,True):
        m,tr,curve=run(data,dt_ms(start),dt_ms(end),variant,target,hours,stress);m['window']=window;results.append(m)
        all_trades += [{**x,'window':window,'stress':stress} for x in tr]
        all_curve += [{**x,'variant':variant,'window':window,'stress':stress} for x in curve]
        print(variant,window,'stress' if stress else 'base','return',m['net_return_fraction'],'DD',m['max_drawdown_fraction'],'PF',m['profit_factor'],'n',m['trade_count'])
    out=ROOT/'results'/'exit_policy_screen';out.mkdir(exist_ok=True,parents=True)
    doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'engine_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'data'/'raw').glob('*_1h.csv'))+sorted((ROOT/'data'/'processed').glob('*_funding_complete_1h.csv'))},'method':'fixed entry logic and shared 0.25% total open stop risk; no parameter tuning on screened final period; stop prioritized over TP on an ambiguous OHLC bar','variants':VARIANTS,'results':results}
    (out/'metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for name,rows in [('trades.csv',all_trades),('equity.csv',all_curve)]:
        with (out/name).open('w',newline='',encoding='utf8') as f:
            fields=list(dict.fromkeys(k for row in rows for k in row));w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(rows)
    with (out/'metrics_summary.csv').open('w',newline='',encoding='utf8') as f:
        fields=list(results[0]);w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(results)
if __name__=='__main__':main()
