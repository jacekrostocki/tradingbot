#!/usr/bin/env python3
"""Fixed long-only BB/RSI/OBV confirmation screen for breakout/retest."""
from __future__ import annotations
import csv,datetime as dt,hashlib,json,math,statistics
from pathlib import Path
from .backtest import ema
from .hypothesis_filter_screen import prep,run
from .portfolio_momentum import ASSETS,dt_ms
ROOT=Path(__file__).resolve().parents[1]
FILTERS=('long_only','long_only_bb','long_only_rsi50','long_only_obv5','long_only_bb_rsi_obv')
WINDOWS=(('funding_era','2025-10-30T00:00:00Z','2026-11-02T00:00:00Z'),('wf_1','2025-10-30T00:00:00Z','2026-02-01T00:00:00Z'),('wf_2','2026-02-01T00:00:00Z','2026-05-22T00:00:00Z'),('final_holdout_screened','2026-05-22T00:00:00Z','2026-11-02T00:00:00Z'))

def rsi(cl,n=14):
 out=[None]*len(cl);g=l=0.0
 if len(cl)<=n:return out
 for i in range(1,n+1):
  d=cl[i]-cl[i-1];g+=max(d,0);l+=max(-d,0)
 g/=n;l/=n;out[n]=100 if l==0 else 100-100/(1+g/l)
 for i in range(n+1,len(cl)):
  d=cl[i]-cl[i-1];g=(g*(n-1)+max(d,0))/n;l=(l*(n-1)+max(-d,0))/n;out[i]=100 if l==0 else 100-100/(1+g/l)
 return out

def confirm_arrays(bars):
 cl=[x['close'] for x in bars];vol=[x['volume'] for x in bars];bb=[False]*len(cl)
 # Prior completed candle must close outside its contemporaneous 20-period, 2-sigma band.
 for i in range(20,len(cl)):
  w=cl[i-20:i];mu=sum(w)/20;sd=math.sqrt(sum((v-mu)**2 for v in w)/20)
  bb[i]=cl[i-1]>mu+2*sd
 rs=rsi(cl);obv=[0.0]*len(cl)
 for i in range(1,len(cl)):
  obv[i]=obv[i-1]+(vol[i] if cl[i]>cl[i-1] else (-vol[i] if cl[i]<cl[i-1] else 0))
 obv5=[False]*len(cl)
 for i in range(5,len(cl)):obv5[i]=obv[i]>obv[i-5]
 rsi50=[x is not None and x>=50 for x in rs]
 return bb,rsi50,obv5

def variant_data(base,variant):
 result={}
 for a,m in base.items():
  bars=m['bars'];bb,r50,o5=confirm_arrays(bars);s=[]
  for i,side in enumerate(m['sig']):
   ok=(side==1)
   if variant in ('long_only_bb','long_only_bb_rsi_obv'):ok=ok and bb[i]
   if variant in ('long_only_rsi50','long_only_bb_rsi_obv'):ok=ok and r50[i]
   if variant in ('long_only_obv5','long_only_bb_rsi_obv'):ok=ok and o5[i]
   s.append(1 if ok else 0)
  result[a]={**m,'sig':s}
 return result

def main():
 base=prep();metrics=[];trades=[];curves=[]
 for filt in FILTERS:
  data=variant_data(base,filt)
  for name,a,b in WINDOWS:
   for stress in (False,True):
    met,tr,curve=run(data,'long_only',dt_ms(a),dt_ms(b),stress);met['filter']=filt;met['window']=name;metrics.append(met)
    trades += [{**x,'filter':filt,'window':name,'stress':stress} for x in tr]
    curves += [{**x,'filter':filt,'window':name,'stress':stress} for x in curve]
 out=ROOT/'results';out.mkdir(exist_ok=True)
 doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'base_signal_sha256':hashlib.sha256((ROOT/'src'/'backtest.py').read_bytes()).hexdigest(),'filter_definition':{'bb':'prior completed 1h close above SMA20 + 2 population standard deviations','rsi':'Wilder RSI(14) at retest close >= 50','obv':'OBV at retest close greater than OBV 5 bars earlier','combined':'all three confirmations; long-only'},'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'data'/'raw').glob('*_1h.csv'))},'results':metrics}
 (out/'indicator_confirmation_metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
 daily={}
 for r in curves:
  day=dt.datetime.fromtimestamp(r['timestamp_ms']/1000,dt.timezone.utc).date().isoformat();daily[(r['filter'],r['window'],r['stress'],day)]=r
 for fname,rows in [('indicator_confirmation_trades.csv',trades),('indicator_confirmation_equity.csv',curves),('indicator_confirmation_equity_daily.csv',list(daily.values()))]:
  with (out/fname).open('w',newline='',encoding='utf8') as f:fields=list(dict.fromkeys(k for row in rows for k in row));w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 for x in metrics:
  if x['window']=='funding_era':print(x['filter'],'stress' if x['stress'] else 'base',x['net_return_fraction'],'PF',x['profit_factor'],'DD',x['max_drawdown_fraction'],'trades',x['trade_count'])
if __name__=='__main__':main()
