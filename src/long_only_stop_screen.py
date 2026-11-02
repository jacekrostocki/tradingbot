#!/usr/bin/env python3
"""Long-only breakout/retest stop-width sensitivity, fixed risk budget."""
from __future__ import annotations
import csv,datetime as dt,hashlib,json,math
from pathlib import Path
from .hypothesis_filter_screen import prep
from .portfolio_momentum import INITIAL,FEE,BASE_FRICTION,STRESS_FRICTION,MOMENTUM_LOOKBACK,dt_ms,utc
ROOT=Path(__file__).resolve().parents[1]
STOPS=(2.0,3.0)
WINDOWS=(('funding_era','2025-10-30T00:00:00Z','2026-11-02T00:00:00Z'),('wf_1','2025-10-30T00:00:00Z','2026-02-01T00:00:00Z'),('wf_2','2026-02-01T00:00:00Z','2026-05-22T00:00:00Z'),('final_holdout_screened','2026-05-22T00:00:00Z','2026-11-02T00:00:00Z'))
RISK=.0025;NOTIONAL=.75;DAILY=-.01;WEEKLY=-.03;DD=-.06

def run(data,stop_mult,lo_ms,hi_ms,stress=False):
 times=[r['timestamp_ms'] for r in data['BTC']['bars']];lo=next(i for i,t in enumerate(times) if t>=lo_ms);hi=next((i for i,t in enumerate(times) if t>=hi_ms),len(times));fr=STRESS_FRICTION if stress else BASE_FRICTION
 eq=INITIAL;peak=INITIAL;maxdd=0.;pos=None;trades=[];curve=[];funded=missing=0;deq=weq=INITIAL;day=week=None
 for i in range(max(lo,MOMENTUM_LOOKBACK+1,201),min(hi,len(times)-1)):
  t=times[i];d=t//86400000;w=t//(7*86400000)
  if d!=day:day=d;deq=eq
  if w!=week:week=w;weq=eq
  if pos:
   m=data[pos['asset']];b=m['bars'][i];rate=m['fund'].get(t)
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
    if i==hi-1:px=b['close'];why='period_end'
   if px is not None:
    out=px*(1-fr*pos['side']);gross=pos['side']*(out-pos['entry'])*pos['qty'];fees=pos['qty']*(pos['entry']+out)*FEE;net=gross-fees+pos['funding'];eq+=net;pos.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason=why,equity=eq);trades.append(pos);pos=None
  mark=eq
  if pos:
   b=data[pos['asset']]['bars'][i];adv=b['low'] if pos['side']==1 else b['high'];mark+=pos['side']*(adv-pos['entry'])*pos['qty']-pos['qty']*(pos['entry']+adv)*FEE+pos['funding']
  peak=max(peak,mark);maxdd=min(maxdd,mark/peak-1)
  if pos is None and i<hi-1 and mark/deq-1>DAILY and mark/weq-1>WEEKLY and mark/peak-1>DD:
   c=[]
   for a,m in data.items():
    if m['sig'][i]!=1:continue
    mom=m['bars'][i]['close']/m['bars'][i-MOMENTUM_LOOKBACK]['close']-1
    if mom>0:c.append((mom,a))
   if c:
    mom,a=max(c);m=data[a];dist=stop_mult*m['atr'][i];entry=m['bars'][i+1]['open']*(1+fr);rf=dist/entry+2*(FEE+fr);notional=min(eq*NOTIONAL,eq*RISK/rf)
    if notional>=10:pos={'asset':a,'strategy':f'long_only_stop_{stop_mult}atr','side':1,'momentum_30d':mom,'signal_ms':t,'entry_ms':times[i+1],'entry':entry,'qty':notional/entry,'notional':notional,'stop':entry-dist,'risk_dist':dist,'extreme':entry,'trail_active':False,'funding':0.,'missing_funding':0}
  curve.append({'timestamp_ms':t,'equity_usd':eq,'adverse_mark_equity_usd':mark,'open_asset':pos['asset'] if pos else '', 'stop_atr':stop_mult})
 if pos:
  b=data[pos['asset']]['bars'][min(hi,len(times))-1];out=b['close']*(1-fr);gross=out-pos['entry'];fees=pos['qty']*(pos['entry']+out)*FEE;net=gross*pos['qty']-fees+pos['funding'];eq+=net;pos.update(exit_ms=b['timestamp_ms'],exit=out,gross=gross*pos['qty'],fees=fees,net=net,reason='period_end',equity=eq);trades.append(pos)
 wins=[x['net'] for x in trades if x['net']>0];loss=[x['net'] for x in trades if x['net']<=0];pf=sum(wins)/abs(sum(loss)) if loss and sum(loss) else ('inf' if wins else 0)
 return {'start_utc':utc(times[lo]),'end_utc':utc(times[min(hi,len(times)-1)]),'stop_atr':stop_mult,'stress':stress,'initial_equity_usd':INITIAL,'final_equity_usd':round(eq,4),'net_return_fraction':round(eq/INITIAL-1,6),'net_pnl_usd':round(eq-INITIAL,4),'trade_count':len(trades),'profit_factor':round(pf,4) if isinstance(pf,float) else pf,'win_rate':round(len(wins)/len(trades),4) if trades else 0,'max_drawdown_fraction':round(maxdd,6),'fees_usd':round(sum(x['fees'] for x in trades),4),'funding_usd':round(sum(x['funding'] for x in trades),4),'funding_coverage_fraction':round(funded/max(funded+missing,1),6),'funding_missing_held_hours':missing,'risk_per_trade':RISK,'notional_cap':NOTIONAL},trades,curve

def main():
 data=prep();metrics=[];trades=[];curves=[]
 for stop in STOPS:
  for name,a,b in WINDOWS:
   for stress in (False,True):
    m,tr,eq=run(data,stop,dt_ms(a),dt_ms(b),stress);m['window']=name;metrics.append(m);trades += [{**x,'window':name,'stress':stress} for x in tr];curves += [{**x,'stop_atr':stop,'window':name,'stress':stress} for x in eq]
 out=ROOT/'results';out.mkdir(exist_ok=True);doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'source_sha256':hashlib.sha256((ROOT/'src'/'backtest.py').read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'data'/'raw').glob('*_1h.csv'))},'results':metrics};(out/'long_only_stop_metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
 for f,rows in [('long_only_stop_trades.csv',trades),('long_only_stop_equity.csv',curves)]:
  with (out/f).open('w',newline='',encoding='utf8') as o:fields=list(dict.fromkeys(k for r in rows for k in r));w=csv.DictWriter(o,fieldnames=fields);w.writeheader();w.writerows(rows)
 for x in metrics:
  if x['window']=='funding_era':print(x['stop_atr'],'stress' if x['stress'] else 'base',x['net_return_fraction'],'PF',x['profit_factor'],'DD',x['max_drawdown_fraction'],'trades',x['trade_count'])
if __name__=='__main__':main()
