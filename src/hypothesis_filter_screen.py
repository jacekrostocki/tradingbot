#!/usr/bin/env python3
"""Preregistered 1h breakout/retest filters: long-only, volume, BTC regime."""
from __future__ import annotations
import csv,datetime as dt,hashlib,json,math,statistics
from pathlib import Path
from .backtest import signals
from .portfolio_momentum import ASSETS,INITIAL,FEE,BASE_FRICTION,STRESS_FRICTION,MOMENTUM_LOOKBACK,dt_ms,utc
ROOT=Path(__file__).resolve().parents[1]
FILTERS=('baseline','long_only','volume_1p5x','btc_regime','long_only_volume_1p5x')
WINDOWS=(('funding_era','2025-10-30T00:00:00Z','2026-11-02T00:00:00Z'),('wf_1','2025-10-30T00:00:00Z','2026-02-01T00:00:00Z'),('wf_2','2026-02-01T00:00:00Z','2026-05-22T00:00:00Z'),('final_holdout_screened','2026-05-22T00:00:00Z','2026-11-02T00:00:00Z'))
RISK=.0025;NOTIONAL=.75;DAILY=-.01;WEEKLY=-.03;DD=-.06

def prep():
 d={}
 for a in ASSETS:
  h,atr,tr,sig,fund=signals(a,'breakout_retest');d[a]={'bars':h,'atr':atr,'trend':tr,'sig':sig,'fund':fund}
 return d

def passes(data,asset,i,variant):
 m=data[asset];side=m['sig'][i]
 if not side:return 0
 if variant in ('long_only','long_only_volume_1p5x') and side<0:return 0
 if variant in ('volume_1p5x','long_only_volume_1p5x'):
  vol=m['bars'][i]['volume'];hist=[r['volume'] for r in m['bars'][i-24:i]]
  if not hist or vol<1.5*(sum(hist)/len(hist)):return 0
 if variant=='btc_regime' and data['BTC']['trend'][i]!=side:return 0
 return side

def run(data,variant,lo_ms,hi_ms,stress=False):
 times=[r['timestamp_ms'] for r in data['BTC']['bars']];lo=next(i for i,t in enumerate(times) if t>=lo_ms);hi=next((i for i,t in enumerate(times) if t>=hi_ms),len(times));fr=STRESS_FRICTION if stress else BASE_FRICTION
 eq=INITIAL;peak=INITIAL;dd=0.;pos=None;trades=[];curve=[];funded=missing=0;dayeq=weekeq=INITIAL;dayid=weekid=None
 for i in range(max(lo,MOMENTUM_LOOKBACK+1,201),min(hi,len(times)-1)):
  t=times[i];day=t//86400000;week=t//(7*86400000)
  if day!=dayid:dayid=day;dayeq=eq
  if week!=weekid:weekid=week;weekeq=eq
  if pos:
   m=data[pos['asset']];b=m['bars'][i];rate=m['fund'].get(t)
   if rate is None:missing+=1;pos['missing_funding']+=1
   else:funded+=1;pos['funding']+=-pos['side']*rate*pos['qty']*pos['entry']
   hit=b['low']<=pos['stop'] if pos['side']==1 else b['high']>=pos['stop'];flip=m['trend'][i]==-pos['side'];px=None;reason=''
   if hit:px=pos['stop'];reason='stop'
   elif flip:px=b['open'];reason='trend_flip'
   else:
    fav=b['high']-pos['entry'] if pos['side']==1 else pos['entry']-b['low']
    if fav>=pos['risk_dist']:pos['trail_active']=True
    if pos['trail_active']:
     cand=pos['extreme']-3*m['atr'][i] if pos['side']==1 else pos['extreme']+3*m['atr'][i]
     pos['stop']=max(pos['stop'],cand) if pos['side']==1 else min(pos['stop'],cand)
    pos['extreme']=max(pos['extreme'],b['high']) if pos['side']==1 else min(pos['extreme'],b['low'])
    if i==hi-1:px=b['close'];reason='period_end'
   if px is not None:
    exitpx=px*(1-fr*pos['side']);gross=pos['side']*(exitpx-pos['entry'])*pos['qty'];fees=pos['qty']*(pos['entry']+exitpx)*FEE;net=gross-fees+pos['funding'];eq+=net;pos.update(exit_ms=t,exit=exitpx,gross=gross,fees=fees,net=net,reason=reason,equity=eq);trades.append(pos);pos=None
  mark=eq
  if pos:
   b=data[pos['asset']]['bars'][i];adv=b['low'] if pos['side']==1 else b['high'];mark+=pos['side']*(adv-pos['entry'])*pos['qty']-pos['qty']*(pos['entry']+adv)*FEE+pos['funding']
  peak=max(peak,mark);dd=min(dd,mark/peak-1)
  if pos is None and i<hi-1 and mark/dayeq-1>DAILY and mark/weekeq-1>WEEKLY and mark/peak-1>DD:
   cand=[]
   for a,m in data.items():
    side=passes(data,a,i,variant)
    if side:
     score=side*(m['bars'][i]['close']/m['bars'][i-MOMENTUM_LOOKBACK]['close']-1)
     if score>0:cand.append((score,a,side))
   if cand:
    score,a,side=max(cand);m=data[a];dist=2*m['atr'][i];entry=m['bars'][i+1]['open']*(1+fr*side);rf=dist/entry+2*(FEE+fr);notional=min(eq*NOTIONAL,eq*RISK/rf)
    if notional>=10:pos={'asset':a,'strategy':variant,'side':side,'momentum_30d':score,'signal_ms':t,'entry_ms':times[i+1],'entry':entry,'qty':notional/entry,'notional':notional,'stop':entry-side*dist,'risk_dist':dist,'extreme':entry,'trail_active':False,'funding':0.,'missing_funding':0}
  curve.append({'timestamp_ms':t,'equity_usd':eq,'adverse_mark_equity_usd':mark,'open_asset':pos['asset'] if pos else ''})
 if pos:
  b=data[pos['asset']]['bars'][min(hi,len(times))-1];px=b['close']*(1-fr*pos['side']);gross=pos['side']*(px-pos['entry'])*pos['qty'];fees=pos['qty']*(pos['entry']+px)*FEE;net=gross-fees+pos['funding'];eq+=net;pos.update(exit_ms=b['timestamp_ms'],exit=px,gross=gross,fees=fees,net=net,reason='period_end',equity=eq);trades.append(pos)
 wins=[x['net'] for x in trades if x['net']>0];loss=[x['net'] for x in trades if x['net']<=0];pf=sum(wins)/abs(sum(loss)) if loss and sum(loss) else ('inf' if wins else 0)
 return {'start_utc':utc(times[lo]),'end_utc':utc(times[min(hi,len(times)-1)]),'filter':variant,'stress':stress,'initial_equity_usd':INITIAL,'final_equity_usd':round(eq,4),'net_return_fraction':round(eq/INITIAL-1,6),'net_pnl_usd':round(eq-INITIAL,4),'trade_count':len(trades),'profit_factor':round(pf,4) if isinstance(pf,float) else pf,'win_rate':round(len(wins)/len(trades),4) if trades else 0,'max_drawdown_fraction':round(dd,6),'fees_usd':round(sum(x['fees'] for x in trades),4),'funding_usd':round(sum(x['funding'] for x in trades),4),'funding_coverage_fraction':round(funded/max(funded+missing,1),6),'funding_missing_held_hours':missing,'risk_per_trade':RISK,'notional_cap':NOTIONAL},trades,curve

def main():
 data=prep();metrics=[];trades=[];curves=[]
 for variant in FILTERS:
  for name,a,b in WINDOWS:
   for stress in (False,True):
    m,tr,eq=run(data,variant,dt_ms(a),dt_ms(b),stress);m['window']=name;metrics.append(m);trades += [{**x,'window':name,'stress':stress} for x in tr];curves += [{**x,'filter':variant,'window':name,'stress':stress} for x in eq]
 out=ROOT/'results';out.mkdir(exist_ok=True);doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'signal_code_sha256':hashlib.sha256((ROOT/'src'/'backtest.py').read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'data'/'raw').glob('*_1h.csv'))},'results':metrics};(out/'filter_hypothesis_metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
 # Daily samples keep the archived equity curve compact while preserving every scenario.
 daily={}
 for row in curves:
  day=dt.datetime.fromtimestamp(row['timestamp_ms']/1000,dt.timezone.utc).date().isoformat()
  daily[(row['filter'],row['window'],row['stress'],day)]=row
 daily_rows=list(daily.values())
 for fname,rows in [('filter_hypothesis_trades.csv',trades),('filter_hypothesis_equity.csv',curves),('filter_hypothesis_equity_daily.csv',daily_rows)]:
  with (out/fname).open('w',newline='',encoding='utf8') as f:fields=list(dict.fromkeys(k for r in rows for k in r));w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 for x in metrics:
  if x['window']=='funding_era':print(x['filter'],'stress' if x['stress'] else 'base',x['net_return_fraction'],'PF',x['profit_factor'],'DD',x['max_drawdown_fraction'],'trades',x['trade_count'])
if __name__=='__main__':main()
