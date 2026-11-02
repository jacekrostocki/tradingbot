#!/usr/bin/env python3
"""Test a fixed 5m Donchian continuation hypothesis with conservative replay."""
from __future__ import annotations
import bisect,csv,datetime as dt,hashlib,json,math,statistics
from pathlib import Path
from .backtest import load
from .intrabar_execution_screen import bars5,WINDOWS,RISK,NOTIONAL_CAP,HOUR,BAR5
from .portfolio_momentum import ASSETS,INITIAL,FEE,BASE_FRICTION,STRESS_FRICTION,MOMENTUM_LOOKBACK,dt_ms,utc
from .portfolio_concurrency import DAILY_STOP,WEEKLY_STOP,DD_STOP

ROOT=Path(__file__).resolve().parents[1];LOOKBACK=48;ATR_N=14;MAX_HOLD=72*HOUR

def atr5(rows):
    out=[0.0]*len(rows);sm=0.0;q=[];prev=None
    for i,r in enumerate(rows):
        tr=max(r['high']-r['low'],abs(r['high']-(prev if prev is not None else r['close'])),abs(r['low']-(prev if prev is not None else r['close'])))
        q.append(tr);sm+=tr
        if len(q)>ATR_N:sm-=q.pop(0)
        if len(q)==ATR_N:out[i]=sm/ATR_N
        prev=r['close']
    return out

def prep():
    d={}
    for a in ASSETS:
        bars=bars5(a);h1,h4,fund=load(a);atr=atr5(bars)
        close=[r['close'] for r in h4];fast=[None]*len(close);slow=[None]*len(close)
        for target,n in ((fast,50),(slow,200)):
            alpha=2/(n+1);v=None
            for i,x in enumerate(close):v=x if v is None else alpha*x+(1-alpha)*v;target[i]=v
        trends=[];ready=[];direction=0;j=0
        h4_avail=[int(x['timestamp_ms'])+4*HOUR for x in h4]
        for b in bars:
            t=b['timestamp_ms']
            while j<len(h4_avail) and h4_avail[j]<=t:
                direction=1 if fast[j]>slow[j] and close[j]>slow[j] else (-1 if fast[j]<slow[j] and close[j]<slow[j] else 0) if j>=199 else 0;j+=1
            trends.append(direction);ready.append(j>=200)
        # Donchian thresholds exclude the forming/current candle; candidate uses previous close.
        hi=[0.0]*len(bars);lo=[0.0]*len(bars);qhi=[];qlo=[]
        for i,b in enumerate(bars):
            if i>=LOOKBACK:
                old=bars[i-LOOKBACK]
                hi[i]=max(x['high'] for x in bars[i-LOOKBACK:i])
                lo[i]=min(x['low'] for x in bars[i-LOOKBACK:i])
        signal=[0]*len(bars)
        for i in range(LOOKBACK,len(bars)-1):
            if trends[i] and atr[i] and bars[i]['close']>hi[i]:signal[i]=1
            elif trends[i] and atr[i] and bars[i]['close']<lo[i]:signal[i]=-1
            if signal[i] and signal[i]!=trends[i]:signal[i]=0
        h1ts=[int(x['timestamp_ms']) for x in h1]
        # Cross-asset candidate ranking uses only the prior completed 1h close.
        d[a]={'bars':bars,'atr':atr,'trend':trends,'trend_ready':ready,'sig':signal,'h1':h1,'h1ts':h1ts,'fund':fund}
    ts=[x['timestamp_ms'] for x in d['BTC']['bars']]
    if any(y-x!=BAR5 for x,y in zip(ts,ts[1:])):raise ValueError('5m grid has gaps')
    if any([x['timestamp_ms'] for x in v['bars']]!=ts for v in d.values()):raise ValueError('cross-asset 5m grids differ')
    return d

def run(data,start_ms,end_ms,stress=False):
    ts=[r['timestamp_ms'] for r in data['BTC']['bars']];lo=bisect.bisect_left(ts,start_ms);hi=bisect.bisect_left(ts,end_ms)
    friction=STRESS_FRICTION if stress else BASE_FRICTION;eq=peak=INITIAL;dd=0.;pos=None;trades=[];curve=[];last_mark=INITIAL;day0=week0=INITIAL;day_id=week_id=None;halt_dd=False;funded=missing=0;kills={'daily':0,'weekly':0,'drawdown':0}
    for k in range(lo,hi):
        t=ts[k];day=t//86_400_000;week=(day+3)//7
        if day!=day_id:day_id=day;day0=last_mark
        if week!=week_id:week_id=week;week0=last_mark
        new_entry=False
        if pos is None and not halt_dd and eq/day0-1>DAILY_STOP and eq/week0-1>WEEKLY_STOP and eq/peak-1>DD_STOP and k>lo:
            cs=[]
            for a,m in data.items():
                i=k-1;side=m['sig'][i]
                if not side or i<LOOKBACK:continue
                j=bisect.bisect_left(m['h1ts'],t)-1
                if j<MOMENTUM_LOOKBACK or int(m['h1'][j]['timestamp_ms'])+HOUR>t:continue
                mom=side*(float(m['h1'][j]['close'])/float(m['h1'][j-MOMENTUM_LOOKBACK]['close'])-1)
                if mom>0:cs.append((mom,a,side,i))
            if cs:
                mom,a,side,i=max(cs);m=data[a];bar=m['bars'][k];entry=bar['open']*(1+friction*side);dist=2*m['atr'][i]
                if dist>0 and (bar['open']>entry-dist if side==1 else bar['open']<entry+dist):
                    riskfrac=dist/entry+2*(FEE+friction);notional=min(eq*NOTIONAL_CAP,eq*RISK/riskfrac)
                    if notional>=10:
                        pos={'asset':a,'strategy':'5m_donchian48_4h_trend_30d_mom','side':side,'momentum_30d':mom,'signal_ms':ts[i],'entry_ms':t,'entry':entry,'qty':notional/entry,'notional':notional,'stop':entry-side*dist,'risk_dist':dist,'extreme':entry,'trail_active':False,'funding':0.,'missing_funding_hours':0};new_entry=True
        if pos is not None:
            m=data[pos['asset']];b=m['bars'][k];side=pos['side']
            if t%HOUR==0 and not new_entry:
                rate=m['fund'].get(t)
                if rate is None:pos['missing_funding_hours']+=1;missing+=1
                else:pos['funding']+=-side*rate*pos['qty']*pos['entry'];funded+=1
            hit=b['low']<=pos['stop'] if side==1 else b['high']>=pos['stop'];px=None;reason=''
            if hit:px=min(pos['stop'],b['open']) if side==1 else max(pos['stop'],b['open']);reason='stop_5m'
            elif m['trend'][k]==-side:px=b['open'];reason='4h_trend_flip'
            elif t-pos['entry_ms']>=MAX_HOLD:px=b['open'];reason='time_stop_72h'
            else:
                fav=b['high']-pos['entry'] if side==1 else pos['entry']-b['low']
                if fav>=pos['risk_dist']:pos['trail_active']=True
                if pos['trail_active'] and m['atr'][k]:
                    cand=pos['extreme']-3*m['atr'][k] if side==1 else pos['extreme']+3*m['atr'][k]
                    pos['stop']=max(pos['stop'],cand) if side==1 else min(pos['stop'],cand)
                pos['extreme']=max(pos['extreme'],b['high']) if side==1 else min(pos['extreme'],b['low'])
            if px is None and k==hi-1:px=b['close'];reason='period_end'
            if px is not None:
                out=px*(1-friction*side);gross=side*(out-pos['entry'])*pos['qty'];fees=pos['qty']*(pos['entry']+out)*FEE;net=gross-fees+pos['funding'];eq+=net;pos.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason=reason,equity=eq);trades.append(pos);pos=None
        mark=eq
        if pos:
            b=data[pos['asset']]['bars'][k];ad=b['low'] if pos['side']==1 else b['high'];mark+=pos['side']*(ad-pos['entry'])*pos['qty']-pos['qty']*(pos['entry']+ad)*FEE+pos['funding']
        peak=max(peak,mark);dd=min(dd,mark/peak-1);kill=None
        if mark/peak-1<=DD_STOP:halt_dd=True
        if pos is not None:
            if mark/peak-1<=DD_STOP:kill='drawdown'
            elif mark/day0-1<=DAILY_STOP:kill='daily'
            elif mark/week0-1<=WEEKLY_STOP:kill='weekly'
        if kill:
            p=pos;b=data[p['asset']]['bars'][k];side=p['side'];ad=b['low'] if side==1 else b['high'];out=ad*(1-friction*side);gross=side*(out-p['entry'])*p['qty'];fees=p['qty']*(p['entry']+out)*FEE;net=gross-fees+p['funding'];eq+=net;p.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason=kill,equity=eq);trades.append(p);pos=None;kills[kill]+=1;mark=eq
        if t%HOUR==0 or k==hi-1:
            risk=max(0,pos['side']*(pos['entry']-pos['stop'])*pos['qty'])+pos['notional']*2*(FEE+friction) if pos else 0
            curve.append({'timestamp_ms':t,'equity_usd':eq,'adverse_mark_equity_usd':mark,'open_positions':int(pos is not None),'open_stop_risk_usd':risk})
        last_mark=mark
    wins=[x['net'] for x in trades if x['net']>0];loss=[x['net'] for x in trades if x['net']<=0];pf=sum(wins)/abs(sum(loss)) if loss and sum(loss) else 0
    metric={'stress':stress,'window_start_utc':utc(ts[lo]),'window_end_utc':utc(ts[hi-1]),'initial_equity_usd':INITIAL,'final_equity_usd':round(eq,4),'net_return_fraction':round(eq/INITIAL-1,6),'trade_count':len(trades),'expectancy_usd':round(statistics.mean([x['net'] for x in trades]),5) if trades else 0,'profit_factor':round(pf,4),'win_rate':round(len(wins)/len(trades),4) if trades else 0,'max_drawdown_fraction':round(dd,6),'fees_usd':round(sum(x['fees'] for x in trades),4),'funding_usd':round(sum(x['funding'] for x in trades),4),'funding_coverage_fraction':round(funded/max(1,funded+missing),6),'missing_funding_held_hours':missing,'max_positions':max((x['open_positions'] for x in curve),default=0),'max_open_stop_risk_fraction':round(max((x['open_stop_risk_usd'] for x in curve),default=0)/INITIAL,6),'kill_switch_triggers':kills}
    return metric,trades,curve

def main():
    data=prep();results=[];alltr=[];allcurves=[]
    for w,s,e in WINDOWS:
        for stress in (False,True):
            m,tr,curve=run(data,dt_ms(s),dt_ms(e),stress);m['window']=w;results.append(m);alltr += [{**x,'window':w,'stress':stress} for x in tr];allcurves += [{**x,'window':w,'stress':stress} for x in curve]
            print(w,'stress' if stress else 'base',m['net_return_fraction'],'PF',m['profit_factor'],'DD',m['max_drawdown_fraction'],'n',m['trade_count'])
    out=ROOT/'results'/'five_minute_donchian_screen';out.mkdir(parents=True,exist_ok=True)
    files=sorted((ROOT/'data'/'raw').glob('*_5m.csv'))+sorted((ROOT/'data'/'raw').glob('*_1h.csv'))+sorted((ROOT/'data'/'processed').glob('*_funding_complete_1h.csv'))
    doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'hypothesis':'Short-horizon price discovery continuation after 4h Donchian breakout, gated by confirmed 4h EMA trend and same-direction 30d momentum','fixed_parameters':{'donchian_5m_bars':LOOKBACK,'atr_5m_bars':ATR_N,'initial_stop_atr':2,'trail_atr':3,'trail_activates_after_R':1,'max_hold_hours':72,'risk_fraction':RISK,'max_notional_fraction':NOTIONAL_CAP,'slots':1},'execution':'signal on closed 5m, entry next 5m open, trade OHLC stop-first, gap-through stop at bar open, Kraken hourly funding, taker fee 5bp and slippage/spread 3bp base / 7.5bp stress each side; 5m trade candles not mark price','results':results}
    (out/'metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for name,rows in [('trades.csv',alltr),('equity.csv',allcurves)]:
        with (out/name).open('w',newline='',encoding='utf8') as f:
            fields=list(dict.fromkeys(k for row in rows for k in row));wr=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');wr.writeheader();wr.writerows(rows)
if __name__=='__main__':main()
