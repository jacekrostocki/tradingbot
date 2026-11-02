#!/usr/bin/env python3
"""Fixed-cost lookback sensitivity for breakout/retest with 4h trend filter."""
from __future__ import annotations
import csv,datetime as dt,hashlib,json,math,statistics
from pathlib import Path
from .backtest import load,atr,ema,trend_filter
from .portfolio_momentum import ASSETS,INITIAL,FEE,BASE_FRICTION,STRESS_FRICTION,MOMENTUM_LOOKBACK,dt_ms,utc
ROOT=Path(__file__).resolve().parents[1]
LOOKBACKS=(24,72,168)
WINDOWS=(('funding_era','2025-10-30T00:00:00Z','2026-11-02T00:00:00Z'),('wf_1','2025-10-30T00:00:00Z','2026-02-01T00:00:00Z'),('wf_2','2026-02-01T00:00:00Z','2026-05-22T00:00:00Z'),('final_holdout_screened','2026-05-22T00:00:00Z','2026-11-02T00:00:00Z'))
RISK=.0025;NOTIONAL=.75;DAILY=-.01;WEEKLY=-.03;DD=-.06

def prepare():
    out={}
    for asset in ASSETS:
        h1,h4,fund=load(asset);cl=[x['close'] for x in h1];hi=[x['high'] for x in h1];lo=[x['low'] for x in h1];a=atr(h1);trend=trend_filter(h1,h4);signals={}
        for n in LOOKBACKS:
            sig=[0]*len(h1)
            for i in range(max(201,n+1),len(h1)-1):
                side=trend[i]
                if not side or not a[i] or a[i]<=0:continue
                upper=max(hi[i-n-1:i-1]);lower=min(lo[i-n-1:i-1])
                broke=cl[i-1]>upper if side==1 else cl[i-1]<lower
                touched=lo[i]<=upper+.25*a[i] if side==1 else hi[i]>=lower-.25*a[i]
                held=cl[i]>upper if side==1 else cl[i]<lower
                if broke and touched and held:sig[i]=side
            signals[n]=sig
        out[asset]={'bars':h1,'atr':a,'trend':trend,'signals':signals,'funding':fund}
    return out

def run(data,n,start_ms,end_ms,stress=False):
    ts=[x['timestamp_ms'] for x in data['BTC']['bars']];start=next(i for i,t in enumerate(ts) if t>=start_ms);stop=next((i for i,t in enumerate(ts) if t>=end_ms),len(ts));fr=STRESS_FRICTION if stress else BASE_FRICTION
    eq=INITIAL;peak=INITIAL;maxdd=0.;pos=None;trades=[];curve=[];funded=missing=0;dayeq=weekeq=INITIAL;dayid=weekid=None
    for i in range(max(start,MOMENTUM_LOOKBACK+1,201),min(stop,len(ts)-1)):
        t=ts[i];day=t//86400000;week=t//(7*86400000)
        if day!=dayid:dayid=day;dayeq=eq
        if week!=weekid:weekid=week;weekeq=eq
        if pos:
            m=data[pos['asset']];b=m['bars'][i];f=m['funding'];rate=f.get(t)
            if rate is None:missing+=1;pos['missing_funding']+=1
            else:funded+=1;pos['funding']+=-pos['side']*rate*pos['qty']*pos['entry']
            hit=b['low']<=pos['stop'] if pos['side']==1 else b['high']>=pos['stop'];flip=m['trend'][i]==-pos['side'];px=None;why=''
            if hit:px=pos['stop'];why='stop'
            elif flip:px=b['open'];why='trend_flip'
            else:
                fav=b['high']-pos['entry'] if pos['side']==1 else pos['entry']-b['low']
                if fav>=pos['risk_dist']:pos['trail_active']=True
                if pos['trail_active']:
                    cand=pos['extreme']-3*m['atr'][i] if pos['side']==1 else pos['extreme']+3*m['atr'][i]
                    pos['stop']=max(pos['stop'],cand) if pos['side']==1 else min(pos['stop'],cand)
                pos['extreme']=max(pos['extreme'],b['high']) if pos['side']==1 else min(pos['extreme'],b['low'])
                if i==stop-1:px=b['close'];why='period_end'
            if px is not None:
                exitpx=px*(1-fr*pos['side']);gross=pos['side']*(exitpx-pos['entry'])*pos['qty'];fees=pos['qty']*(pos['entry']+exitpx)*FEE;net=gross-fees+pos['funding'];eq+=net;pos.update(exit_ms=t,exit=exitpx,gross=gross,fees=fees,net=net,reason=why,equity=eq);trades.append(pos);pos=None
        mark=eq
        if pos:
            b=data[pos['asset']]['bars'][i];adv=b['low'] if pos['side']==1 else b['high'];mark+=pos['side']*(adv-pos['entry'])*pos['qty']-pos['qty']*(pos['entry']+adv)*FEE+pos['funding']
        peak=max(peak,mark);maxdd=min(maxdd,mark/peak-1)
        if pos is None and i<stop-1 and mark/dayeq-1>DAILY and mark/weekeq-1>WEEKLY and mark/peak-1>DD:
            cand=[]
            for a,m in data.items():
                side=m['signals'][n][i]
                if not side:continue
                score=side*(m['bars'][i]['close']/m['bars'][i-MOMENTUM_LOOKBACK]['close']-1)
                if score>0:cand.append((score,a,side))
            if cand:
                score,asset,side=max(cand);m=data[asset];dist=2*m['atr'][i];entry=m['bars'][i+1]['open']*(1+fr*side);rf=dist/entry+2*(FEE+fr);notional=min(eq*NOTIONAL,eq*RISK/rf)
                if notional>=10:pos={'asset':asset,'strategy':f'breakout_retest_{n}h','side':side,'momentum_30d':score,'signal_ms':t,'entry_ms':ts[i+1],'entry':entry,'qty':notional/entry,'notional':notional,'stop':entry-side*dist,'risk_dist':dist,'extreme':entry,'trail_active':False,'funding':0.,'missing_funding':0}
        curve.append({'timestamp_ms':t,'equity_usd':eq,'adverse_mark_equity_usd':mark})
    if pos:
        b=data[pos['asset']]['bars'][min(stop,len(ts))-1];px=b['close']*(1-fr*pos['side']);gross=pos['side']*(px-pos['entry'])*pos['qty'];fees=pos['qty']*(pos['entry']+px)*FEE;net=gross-fees+pos['funding'];eq+=net;pos.update(exit_ms=b['timestamp_ms'],exit=px,gross=gross,fees=fees,net=net,reason='period_end',equity=eq);trades.append(pos)
    wins=[x['net'] for x in trades if x['net']>0];loss=[x['net'] for x in trades if x['net']<=0];pf=sum(wins)/abs(sum(loss)) if loss and sum(loss) else ('inf' if wins else 0)
    return {'start_utc':utc(ts[start]),'end_utc':utc(ts[min(stop,len(ts)-1)]),'lookback_hours':n,'stress':stress,'initial_equity_usd':INITIAL,'final_equity_usd':round(eq,4),'net_return_fraction':round(eq/INITIAL-1,6),'net_pnl_usd':round(eq-INITIAL,4),'trade_count':len(trades),'profit_factor':round(pf,4) if isinstance(pf,float) else pf,'win_rate':round(len(wins)/len(trades),4) if trades else 0,'max_drawdown_fraction':round(maxdd,6),'fees_usd':round(sum(x['fees'] for x in trades),4),'funding_usd':round(sum(x['funding'] for x in trades),4),'funding_coverage_fraction':round(funded/max(funded+missing,1),6),'funding_missing_held_hours':missing,'risk_per_trade':RISK,'notional_cap':NOTIONAL,'daily_entry_halt':DAILY,'weekly_entry_halt':WEEKLY,'drawdown_entry_halt':DD},trades,curve

def main():
    data=prepare();metrics=[];trades=[];curves=[]
    for n in LOOKBACKS:
      for name,a,b in WINDOWS:
       for stress in (False,True):
        m,tr,eq=run(data,n,dt_ms(a),dt_ms(b),stress);m['window']=name;metrics.append(m);trades += [{**x,'window':name,'stress':stress} for x in tr];curves += [{**x,'window':name,'stress':stress} for x in eq]
    out=ROOT/'results';out.mkdir(exist_ok=True);doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'data'/'raw').glob('*_1h.csv'))+sorted((ROOT/'data'/'raw').glob('*_4h.csv'))},'results':metrics};(out/'retest_lookback_metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for fname,rows in [('retest_lookback_trades.csv',trades),('retest_lookback_equity.csv',curves)]:
        with (out/fname).open('w',newline='',encoding='utf8') as f:fields=list(dict.fromkeys(k for r in rows for k in r));w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    for x in metrics:
        if x['window']=='funding_era':print(x['lookback_hours'],'stress' if x['stress'] else 'base',x['net_return_fraction'],'PF',x['profit_factor'],'DD',x['max_drawdown_fraction'],'trades',x['trade_count'])
if __name__=='__main__':main()
