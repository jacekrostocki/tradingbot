#!/usr/bin/env python3
"""Intraday BB/RSI mean-reversion screen with 4h regime, stops, target and costs."""
from __future__ import annotations
import csv,datetime as dt,hashlib,json,math,statistics
from pathlib import Path
from .backtest import signals
from .portfolio_momentum import ASSETS,INITIAL,FEE,BASE_FRICTION,STRESS_FRICTION,dt_ms,utc
ROOT=Path(__file__).resolve().parents[1]
WINDOWS=(('funding_era','2025-10-30T00:00:00Z','2026-11-02T00:00:00Z'),('wf_1','2025-10-30T00:00:00Z','2026-02-01T00:00:00Z'),('wf_2','2026-02-01T00:00:00Z','2026-05-22T00:00:00Z'),('final_holdout_screened','2026-05-22T00:00:00Z','2026-11-02T00:00:00Z'))
RISK=.0025;NOTIONAL=.75;DAILY=-.01;WEEKLY=-.03;DD=-.06;MAX_HOLD=24

def rsi14(cl):
 out=[None]*len(cl);n=14
 if len(cl)<=n:return out
 g=sum(max(cl[i]-cl[i-1],0) for i in range(1,n+1))/n;l=sum(max(cl[i-1]-cl[i],0) for i in range(1,n+1))/n
 out[n]=100 if l==0 else 100-100/(1+g/l)
 for i in range(n+1,len(cl)):
  d=cl[i]-cl[i-1];g=(g*(n-1)+max(d,0))/n;l=(l*(n-1)+max(-d,0))/n;out[i]=100 if l==0 else 100-100/(1+g/l)
 return out

def prep():
 data={}
 for a in ASSETS:
  h,atr,trend,_,fund=signals(a,'breakout_retest');cl=[x['close'] for x in h];r=rsi14(cl);mid=[None]*len(h);upper=[None]*len(h);lower=[None]*len(h)
  for i in range(19,len(h)):
   w=cl[i-19:i+1];m=sum(w)/20;s=math.sqrt(sum((x-m)**2 for x in w)/20);mid[i]=m;upper[i]=m+2*s;lower[i]=m-2*s
  data[a]={'bars':h,'atr':atr,'trend':trend,'fund':fund,'rsi':r,'mid':mid,'upper':upper,'lower':lower}
 return data

def run(data,lo_ms,hi_ms,stress=False):
 ts=[x['timestamp_ms'] for x in data['BTC']['bars']];lo=next(i for i,t in enumerate(ts) if t>=lo_ms);hi=next((i for i,t in enumerate(ts) if t>=hi_ms),len(ts));fr=STRESS_FRICTION if stress else BASE_FRICTION
 eq=INITIAL;peak=INITIAL;maxdd=0.;pos=None;trades=[];curve=[];funded=missing=0;dayeq=weekeq=INITIAL;dayid=weekid=None
 for i in range(max(lo,200),min(hi,len(ts)-1)):
  t=ts[i];day=t//86400000;week=t//(7*86400000)
  if day!=dayid:dayid=day;dayeq=eq
  if week!=weekid:weekid=week;weekeq=eq
  if pos:
   m=data[pos['asset']];b=m['bars'][i];rate=m['fund'].get(t)
   if rate is None:missing+=1;pos['missing_funding']+=1
   else:funded+=1;pos['funding']+=-pos['side']*rate*pos['qty']*pos['entry']
   hit=b['low']<=pos['stop'] if pos['side']==1 else b['high']>=pos['stop']
   target=b['high']>=pos['target'] if pos['side']==1 else b['low']<=pos['target']
   flip=m['trend'][i]==-pos['side'];px=None;why=''
   if hit:px=pos['stop'];why='stop' # adverse ordering if stop and target both touch within same hourly bar
   elif target:px=pos['target'];why='bb_mid_target'
   elif flip:px=b['open'];why='trend_flip'
   elif i-pos['entry_i']>=MAX_HOLD:px=b['close'];why='time_stop'
   if px is not None:
    out=px*(1-fr*pos['side']);gross=pos['side']*(out-pos['entry'])*pos['qty'];fees=pos['qty']*(pos['entry']+out)*FEE;net=gross-fees+pos['funding'];eq+=net;pos.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason=why,equity=eq);trades.append(pos);pos=None
  mark=eq
  if pos:
   b=data[pos['asset']]['bars'][i];adverse=b['low'] if pos['side']==1 else b['high'];mark+=pos['side']*(adverse-pos['entry'])*pos['qty']-pos['qty']*(pos['entry']+adverse)*FEE+pos['funding']
  peak=max(peak,mark);maxdd=min(maxdd,mark/peak-1)
  if pos is None and i<hi-1 and mark/dayeq-1>DAILY and mark/weekeq-1>WEEKLY and mark/peak-1>DD:
   cands=[]
   for a,m in data.items():
    side=1 if m['trend'][i]==1 and m['rsi'][i] is not None and m['rsi'][i]<30 and m['bars'][i]['close']<m['lower'][i] else (-1 if m['trend'][i]==-1 and m['rsi'][i] is not None and m['rsi'][i]>70 and m['bars'][i]['close']>m['upper'][i] else 0)
    if side:
     extension=(m['lower'][i]-m['bars'][i]['close'])/m['atr'][i] if side==1 else (m['bars'][i]['close']-m['upper'][i])/m['atr'][i]
     cands.append((extension,a,side))
   if cands:
    score,a,side=max(cands);m=data[a];b=m['bars'][i];entry=m['bars'][i+1]['open']*(1+fr*side);target=m['mid'][i];dist=1.5*m['atr'][i]
    if (side==1 and target>entry) or (side==-1 and target<entry):
     rf=dist/entry+2*(FEE+fr);notional=min(eq*NOTIONAL,eq*RISK/rf)
     if notional>=10:pos={'asset':a,'strategy':'bb_rsi_mean_reversion','side':side,'extension_atr':score,'signal_ms':t,'entry_ms':ts[i+1],'entry_i':i+1,'entry':entry,'qty':notional/entry,'notional':notional,'stop':entry-side*dist,'target':target,'funding':0.,'missing_funding':0}
  curve.append({'timestamp_ms':t,'equity_usd':round(eq,6),'adverse_mark_equity_usd':round(mark,6),'open_asset':pos['asset'] if pos else ''})
 if pos:
  b=data[pos['asset']]['bars'][min(hi,len(ts))-1];px=b['close']*(1-fr*pos['side']);gross=pos['side']*(px-pos['entry'])*pos['qty'];fees=pos['qty']*(pos['entry']+px)*FEE;net=gross-fees+pos['funding'];eq+=net;pos.update(exit_ms=b['timestamp_ms'],exit=px,gross=gross,fees=fees,net=net,reason='period_end',equity=eq);trades.append(pos)
 wins=[x['net'] for x in trades if x['net']>0];loss=[x['net'] for x in trades if x['net']<=0];pf=sum(wins)/abs(sum(loss)) if loss and sum(loss) else ('inf' if wins else 0)
 # Weekly mark-to-market return distribution; epoch weeks UTC, matching circuit breaker convention.
 byweek={}
 for q in curve:byweek.setdefault(q['timestamp_ms']//(7*86400000),[]).append(q['adverse_mark_equity_usd'])
 wr=[v[-1]/v[0]-1 for v in byweek.values() if v[0]>0]
 return {'start_utc':utc(ts[lo]),'end_utc':utc(ts[min(hi,len(ts)-1)]),'stress':stress,'initial_equity_usd':INITIAL,'final_equity_usd':round(eq,4),'net_return_fraction':round(eq/INITIAL-1,6),'net_pnl_usd':round(eq-INITIAL,4),'trade_count':len(trades),'profit_factor':round(pf,4) if isinstance(pf,float) else pf,'win_rate':round(len(wins)/len(trades),4) if trades else 0,'max_drawdown_fraction':round(maxdd,6),'fees_usd':round(sum(x['fees'] for x in trades),4),'funding_usd':round(sum(x['funding'] for x in trades),4),'funding_coverage_fraction':round(funded/max(funded+missing,1),6),'funding_missing_held_hours':missing,'weekly_return_mean':round(statistics.mean(wr),6) if wr else 0,'weekly_return_median':round(statistics.median(wr),6) if wr else 0,'weeks_ge_4pct':sum(x>=.04 for x in wr),'weeks_count':len(wr),'weekly_hit_rate_4pct':round(sum(x>=.04 for x in wr)/max(len(wr),1),4),'parameters':{'bb_period':20,'bb_sigma':2,'rsi_period':14,'long_rsi_below':30,'short_rsi_above':70,'trend_filter':'4h EMA50/EMA200 same direction','stop_atr':1.5,'target':'BB middle at signal close','max_hold_hours':MAX_HOLD,'risk_per_trade':RISK,'notional_cap':NOTIONAL}},trades,curve

def main():
 data=prep();metrics=[];trades=[];curves=[]
 for name,a,b in WINDOWS:
  for stress in (False,True):
   m,tr,eq=run(data,dt_ms(a),dt_ms(b),stress);m['window']=name;metrics.append(m);trades += [{**x,'window':name,'stress':stress} for x in tr];curves += [{**x,'window':name,'stress':stress} for x in eq]
 out=ROOT/'results';out.mkdir(exist_ok=True);doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'signal_code_sha256':hashlib.sha256((ROOT/'src'/'backtest.py').read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'data'/'raw').glob('*_1h.csv'))},'results':metrics};(out/'intraday_reversion_metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
 for fn,rows in [('intraday_reversion_trades.csv',trades),('intraday_reversion_equity.csv',curves)]:
  with (out/fn).open('w',newline='',encoding='utf8') as f:fields=list(dict.fromkeys(k for x in rows for k in x));w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 for m in metrics:
  if m['window']=='funding_era':print('stress' if m['stress'] else 'base',m['net_return_fraction'],'PF',m['profit_factor'],'DD',m['max_drawdown_fraction'],'trades',m['trade_count'],'weekly mean/median',m['weekly_return_mean'],m['weekly_return_median'],'weeks >=4%',m['weeks_ge_4pct'],'/',m['weeks_count'])
if __name__=='__main__':main()
