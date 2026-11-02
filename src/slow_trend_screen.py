#!/usr/bin/env python3
"""Low-turnover 4h entry / 1d regime screen, with funding and execution stress."""
from __future__ import annotations
import csv,datetime as dt,hashlib,json,math,statistics
from pathlib import Path
from .backtest import read,ema,atr
from .portfolio_momentum import ASSETS,INITIAL,FEE,BASE_FRICTION,STRESS_FRICTION,dt_ms,utc
ROOT=Path(__file__).resolve().parents[1]
STRATEGIES=('4h_donchian20_daily_trend','4h_breakout_retest20_daily_trend','4h_ema20_pullback_daily_trend')
WINDOWS=(('funding_era','2025-10-30T00:00:00Z','2026-11-02T00:00:00Z'),('wf_1','2025-10-30T00:00:00Z','2026-02-01T00:00:00Z'),('wf_2','2026-02-01T00:00:00Z','2026-05-22T00:00:00Z'),('final_holdout_screened','2026-05-22T00:00:00Z','2026-11-02T00:00:00Z'))
RISK=.0025;NOTIONAL_CAP=.75;DAILY=-.01;WEEKLY=-.03;DD=-.06

def load_market():
    market={}
    for a in ASSETS:
        raw=ROOT/'data'/'raw';h=read(raw/f'kraken_futures_{a}_4h.csv');d=read(raw/f'kraken_futures_{a}_1d.csv');fpath=raw/f'kraken_futures_{a}_funding_1h.csv'
        fund={int(x['timestamp_ms']):float(x['funding_rate']) for x in read(fpath)}
        for r in h+d:
            for k in ('timestamp_ms','open','high','low','close','volume'):r[k]=int(r[k]) if k=='timestamp_ms' else float(r[k])
        c4=[x['close'] for x in h];hi=[x['high'] for x in h];lo=[x['low'] for x in h];a4=atr(h,14);e20=ema(c4,20)
        dc=[x['close'] for x in d];ef=ema(dc,50);es=ema(dc,200);daytr=[]
        for j,x in enumerate(d):daytr.append(1 if j>=199 and ef[j]>es[j] and dc[j]>es[j] else (-1 if j>=199 and ef[j]<es[j] and dc[j]<es[j] else 0))
        # Direction only becomes available at the daily bar's close.
        avail=[(int(x['timestamp_ms'])+86400000,daytr[j]) for j,x in enumerate(d) if j>=199]
        trend=[];j=0;direction=0
        for r in h:
            close_t=r['timestamp_ms']+4*3600000
            while j<len(avail) and avail[j][0]<=close_t:direction=avail[j][1];j+=1
            trend.append(direction)
        sigs={s:[0]*len(h) for s in STRATEGIES}
        for i in range(200,len(h)-1):
            if not a4[i] or a4[i]<=0:continue
            side=trend[i]
            if not side:continue
            upper=max(hi[i-20:i]);lower=min(lo[i-20:i])
            sigs[STRATEGIES[0]][i]=side if (side==1 and c4[i]>upper) or (side==-1 and c4[i]<lower) else 0
            # Previous close must have broken the prior range; current bar must retest and close back beyond it.
            up0=max(hi[i-21:i-1]);dn0=min(lo[i-21:i-1])
            broke=(c4[i-1]>up0) if side==1 else (c4[i-1]<dn0)
            touched=(lo[i]<=up0+.25*a4[i]) if side==1 else (hi[i]>=dn0-.25*a4[i])
            held=(c4[i]>up0) if side==1 else (c4[i]<dn0)
            sigs[STRATEGIES[1]][i]=side if broke and touched and held else 0
            if side==1 and c4[i-1]<e20[i-1] and c4[i]>e20[i] and c4[i]>c4[i-2]:sigs[STRATEGIES[2]][i]=1
            elif side==-1 and c4[i-1]>e20[i-1] and c4[i]<e20[i] and c4[i]<c4[i-2]:sigs[STRATEGIES[2]][i]=-1
        market[a]={'bars':h,'atr':a4,'trend':trend,'signals':sigs,'fund':fund}
    return market

def run(market,strategy,start_ms,end_ms,stress=False):
    times=[x['timestamp_ms'] for x in market['BTC']['bars']];start=next(i for i,t in enumerate(times) if t>=start_ms);stop=next((i for i,t in enumerate(times) if t>=end_ms),len(times));fr=STRESS_FRICTION if stress else BASE_FRICTION
    eq=INITIAL;peak=INITIAL;maxdd=0.;pos=None;trades=[];curve=[];funded=missing=0;dayeq=weekeq=INITIAL;dayid=weekid=None
    for i in range(max(start,200),min(stop,len(times)-1)):
        t=times[i];day=t//86400000;week=t//(7*86400000)
        if day!=dayid:dayid=day;dayeq=eq
        if week!=weekid:weekid=week;weekeq=eq
        if pos:
            m=market[pos['asset']];b=m['bars'][i];a4=m['atr'][i]
            # Charge each of the four hourly funding buckets in this 4h holding interval.
            for hour in range(4):
                rate=m['fund'].get(t+hour*3600000)
                if rate is None:missing+=1;pos['missing_funding']+=1
                else:funded+=1;pos['funding']+=-pos['side']*rate*pos['qty']*pos['entry']
            hit=(b['low']<=pos['stop'] if pos['side']==1 else b['high']>=pos['stop']);flip=m['trend'][i]==-pos['side'];exitpx=None;reason=''
            if hit:exitpx=pos['stop'];reason='stop'
            elif flip:exitpx=b['open'];reason='daily_trend_flip'
            else:
                favorable=(b['high']-pos['entry']) if pos['side']==1 else (pos['entry']-b['low'])
                if favorable>=pos['risk_dist']:pos['trail_active']=True
                if pos['trail_active'] and a4:
                    cand=pos['extreme']-3*a4 if pos['side']==1 else pos['extreme']+3*a4
                    pos['stop']=max(pos['stop'],cand) if pos['side']==1 else min(pos['stop'],cand)
                pos['extreme']=max(pos['extreme'],b['high']) if pos['side']==1 else min(pos['extreme'],b['low'])
                if i==stop-1:exitpx=b['close'];reason='period_end'
            if exitpx is not None:
                px=exitpx*(1-fr*pos['side']);gross=pos['side']*(px-pos['entry'])*pos['qty'];fees=pos['qty']*(pos['entry']+px)*FEE;net=gross-fees+pos['funding'];eq+=net
                pos.update(exit_ms=t+4*3600000,exit=px,gross=gross,fees=fees,net=net,reason=reason,equity=eq);trades.append(pos);pos=None
        mark=eq
        if pos:
            b=market[pos['asset']]['bars'][i];adv=b['low'] if pos['side']==1 else b['high'];mark+=pos['side']*(adv-pos['entry'])*pos['qty']-pos['qty']*(pos['entry']+adv)*FEE+pos['funding']
        peak=max(peak,mark);maxdd=min(maxdd,mark/peak-1)
        if pos is None and i<stop-1 and mark/dayeq-1>DAILY and mark/weekeq-1>WEEKLY and mark/peak-1>DD:
            cand=[]
            for a,m in market.items():
                side=m['signals'][strategy][i]
                if not side:continue
                # Rank by aligned 30-calendar-day return on the 4h series.
                j=max(0,i-180);score=side*(m['bars'][i]['close']/m['bars'][j]['close']-1)
                if score>0:cand.append((score,a,side))
            if cand:
                score,a,side=max(cand);m=market[a];b=m['bars'][i];dist=2*m['atr'][i];entry=m['bars'][i+1]['open']*(1+fr*side);rf=dist/entry+2*(FEE+fr);notional=min(eq*NOTIONAL_CAP,eq*RISK/rf)
                if notional>=10:
                    pos={'asset':a,'strategy':strategy,'side':side,'momentum_30d':score,'signal_ms':t,'entry_ms':times[i+1],'entry':entry,'qty':notional/entry,'notional':notional,'stop':entry-side*dist,'risk_dist':dist,'extreme':entry,'trail_active':False,'funding':0.,'missing_funding':0}
        curve.append({'timestamp_ms':t,'equity_usd':round(eq,6),'adverse_mark_equity_usd':round(mark,6),'open_position':pos['asset'] if pos else ''})
    if pos:
        m=market[pos['asset']];b=m['bars'][min(stop,len(times))-1];px=b['close']*(1-fr*pos['side']);gross=pos['side']*(px-pos['entry'])*pos['qty'];fees=pos['qty']*(pos['entry']+px)*FEE;net=gross-fees+pos['funding'];eq+=net;pos.update(exit_ms=b['timestamp_ms']+4*3600000,exit=px,gross=gross,fees=fees,net=net,reason='period_end',equity=eq);trades.append(pos)
    wins=[x['net'] for x in trades if x['net']>0];loss=[x['net'] for x in trades if x['net']<=0];pf=sum(wins)/abs(sum(loss)) if loss and sum(loss) else ('inf' if wins else 0)
    marks=[x['adverse_mark_equity_usd'] for x in curve];rets=[marks[j]/marks[j-1]-1 for j in range(1,len(marks)) if marks[j-1]>0];sd=statistics.pstdev(rets) if len(rets)>1 else 0;sh=statistics.mean(rets)/sd*math.sqrt(6*365) if sd else 0
    return {'start_utc':utc(times[start]),'end_utc':utc(times[min(stop,len(times)-1)]),'strategy':strategy,'stress':stress,'initial_equity_usd':INITIAL,'final_equity_usd':round(eq,4),'net_return_fraction':round(eq/INITIAL-1,6),'net_pnl_usd':round(eq-INITIAL,4),'trade_count':len(trades),'profit_factor':round(pf,4) if isinstance(pf,float) else pf,'win_rate':round(len(wins)/len(trades),4) if trades else 0,'max_drawdown_fraction':round(maxdd,6),'fees_usd':round(sum(x['fees'] for x in trades),4),'funding_usd':round(sum(x['funding'] for x in trades),4),'funding_coverage_fraction':round(funded/max(funded+missing,1),6),'funding_missing_held_hours':missing,'sharpe_4h_annualized_approx':round(sh,4),'risk_parameters':{'risk_per_trade':RISK,'max_positions_total':1,'notional_cap':NOTIONAL_CAP,'daily_halt':DAILY,'weekly_halt':WEEKLY,'drawdown_halt':DD}},trades,curve

def main():
    mkt=load_market();metrics=[];trades=[];curves=[]
    for strat in STRATEGIES:
      for window,a,b in WINDOWS:
       for stress in (False,True):
        met,tr,eq=run(mkt,strat,dt_ms(a),dt_ms(b),stress);met['window']=window;metrics.append(met);trades += [{**x,'window':window,'stress':stress} for x in tr];curves += [{**x,'window':window,'stress':stress} for x in eq]
    out=ROOT/'results';out.mkdir(exist_ok=True);doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'signal_code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'data'/'raw').glob('*_4h.csv'))+sorted((ROOT/'data'/'raw').glob('*_1d.csv'))+sorted((ROOT/'data'/'raw').glob('*_funding_1h.csv'))},'results':metrics}
    (out/'slow_trend_metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for name,rows in [('slow_trend_trades.csv',trades),('slow_trend_equity.csv',curves)]:
        with (out/name).open('w',newline='',encoding='utf8') as f:fields=list(dict.fromkeys(k for row in rows for k in row));w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    for x in metrics:
        if x['window']=='funding_era':print(x['strategy'],'stress' if x['stress'] else 'base',x['net_return_fraction'],'PF',x['profit_factor'],'DD',x['max_drawdown_fraction'],'trades',x['trade_count'])
if __name__=='__main__':main()
