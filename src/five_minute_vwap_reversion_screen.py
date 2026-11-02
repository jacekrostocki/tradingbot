#!/usr/bin/env python3
"""Fixed 5m volume-weighted fair-value reversion screen in neutral 4h regimes."""
from __future__ import annotations
import bisect,csv,datetime as dt,hashlib,json,math,statistics
from pathlib import Path
from .five_minute_donchian_screen import prep,atr5
from .intrabar_execution_screen import WINDOWS,HOUR,BAR5
from .portfolio_momentum import ASSETS,INITIAL,FEE,BASE_FRICTION,STRESS_FRICTION,RISK,NOTIONAL_CAP,dt_ms,utc
from .portfolio_concurrency import DAILY_STOP,WEEKLY_STOP,DD_STOP

ROOT=Path(__file__).resolve().parents[1];N=48;Z_ENTRY=2.0;ATR_N=14;MAX_HOLD=12*HOUR

def vwap_bands(bars):
    vw=[0.]*len(bars);sd=[0.]*len(bars)
    for i in range(N-1,len(bars)):
        chunk=bars[i-N+1:i+1];vol=sum(x['volume'] for x in chunk)
        if vol<=0:continue
        mean=sum(((x['high']+x['low']+x['close'])/3)*x['volume'] for x in chunk)/vol
        var=sum(x['volume']*((x['high']+x['low']+x['close'])/3-mean)**2 for x in chunk)/vol
        vw[i]=mean;sd[i]=math.sqrt(max(0.,var))
    return vw,sd

def run(data,start_ms,end_ms,stress=False):
    ts=[r['timestamp_ms'] for r in data['BTC']['bars']];lo=bisect.bisect_left(ts,start_ms);hi=bisect.bisect_left(ts,end_ms)
    friction=STRESS_FRICTION if stress else BASE_FRICTION;eq=peak=INITIAL;dd=0.;pos=None;trades=[];curve=[];last_mark=INITIAL;day0=week0=INITIAL;day_id=week_id=None;halt=False;funded=missing=0;kills={'daily':0,'weekly':0,'drawdown':0}
    for k in range(lo,hi):
        t=ts[k];day=t//86_400_000;week=(day+3)//7
        if day!=day_id:day_id=day;day0=last_mark
        if week!=week_id:week_id=week;week0=last_mark
        new_entry=False
        if pos is None and not halt and eq/day0-1>DAILY_STOP and eq/week0-1>WEEKLY_STOP and eq/peak-1>DD_STOP and k>lo:
            cand=[]
            for a,m in data.items():
                i=k-1;b=m['bars'][i];vw=m['vwap'][i];sd=m['sd'][i]
                if not vw or not sd or not m['trend_ready'][i] or m['trend'][i]!=0:continue
                z=(b['close']-vw)/sd
                side=-1 if z>=Z_ENTRY else (1 if z<=-Z_ENTRY else 0)
                if side and m['atr'][i]>0:cand.append((abs(z),a,side,i,z))
            if cand:
                z,a,side,i,zsigned=max(cand);m=data[a];bar=m['bars'][k];entry=bar['open']*(1+friction*side);target=m['vwap'][i];dist=2*m['atr'][i]
                # Skip if the opening gap has already crossed the mean-reversion target.
                favorable=side*(target-entry)
                if favorable>entry*2*(FEE+friction) and dist>0:
                    rf=dist/entry+2*(FEE+friction);notional=min(eq*NOTIONAL_CAP,eq*RISK/rf)
                    if notional>=10:
                        pos={'asset':a,'strategy':'5m_vwap48_2sigma_reversion_4h_neutral','side':side,'entry_z':zsigned,'signal_ms':ts[i],'entry_ms':t,'entry':entry,'target':target,'qty':notional/entry,'notional':notional,'stop':entry-side*dist,'risk_dist':dist,'funding':0.,'missing_funding_hours':0};new_entry=True
        if pos is not None:
            m=data[pos['asset']];b=m['bars'][k];side=pos['side']
            if t%HOUR==0 and not new_entry:
                rate=m['fund'].get(t)
                if rate is None:pos['missing_funding_hours']+=1;missing+=1
                else:pos['funding']+=-side*rate*pos['qty']*pos['entry'];funded+=1
            stop_hit=b['low']<=pos['stop'] if side==1 else b['high']>=pos['stop'];target_hit=b['high']>=pos['target'] if side==1 else b['low']<=pos['target'];px=None;reason=''
            if stop_hit:px=min(pos['stop'],b['open']) if side==1 else max(pos['stop'],b['open']);reason='stop_5m_stop_first'
            elif target_hit:px=pos['target'];reason='vwap_target'
            elif t-pos['entry_ms']>=MAX_HOLD:px=b['open'];reason='time_stop_12h'
            if px is None and k==hi-1:px=b['close'];reason='period_end'
            if px is not None:
                out=px*(1-friction*side);gross=side*(out-pos['entry'])*pos['qty'];fees=pos['qty']*(pos['entry']+out)*FEE;net=gross-fees+pos['funding'];eq+=net;pos.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason=reason,equity=eq);trades.append(pos);pos=None
        mark=eq
        if pos:
            b=data[pos['asset']]['bars'][k];ad=b['low'] if pos['side']==1 else b['high'];mark+=pos['side']*(ad-pos['entry'])*pos['qty']-pos['qty']*(pos['entry']+ad)*FEE+pos['funding']
        peak=max(peak,mark);dd=min(dd,mark/peak-1);kill=None
        if mark/peak-1<=DD_STOP:halt=True
        if pos is not None:
            if mark/peak-1<=DD_STOP:kill='drawdown'
            elif mark/day0-1<=DAILY_STOP:kill='daily'
            elif mark/week0-1<=WEEKLY_STOP:kill='weekly'
        if kill:
            p=pos;b=data[p['asset']]['bars'][k];side=p['side'];ad=b['low'] if side==1 else b['high'];out=ad*(1-friction*side);gross=side*(out-p['entry'])*p['qty'];fees=p['qty']*(p['entry']+out)*FEE;net=gross-fees+p['funding'];eq+=net;p.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason=kill,equity=eq);trades.append(p);pos=None;kills[kill]+=1;mark=eq
        if t%HOUR==0 or k==hi-1:
            risk=(max(0,pos['side']*(pos['entry']-pos['stop'])*pos['qty'])+pos['notional']*2*(FEE+friction)) if pos else 0.
            curve.append({'timestamp_ms':t,'equity_usd':eq,'adverse_mark_equity_usd':mark,'open_positions':int(pos is not None),'open_stop_risk_usd':risk})
        last_mark=mark
    wins=[x['net'] for x in trades if x['net']>0];loss=[x['net'] for x in trades if x['net']<=0];pf=sum(wins)/abs(sum(loss)) if loss and sum(loss) else 0
    metric={'stress':stress,'window_start_utc':utc(ts[lo]),'window_end_utc':utc(ts[hi-1]),'final_equity_usd':round(eq,4),'net_return_fraction':round(eq/INITIAL-1,6),'trade_count':len(trades),'expectancy_usd':round(statistics.mean([x['net'] for x in trades]),5) if trades else 0,'profit_factor':round(pf,4),'win_rate':round(len(wins)/len(trades),4) if trades else 0,'max_drawdown_fraction':round(dd,6),'fees_usd':round(sum(x['fees'] for x in trades),4),'funding_usd':round(sum(x['funding'] for x in trades),4),'funding_coverage_fraction':round(funded/max(1,funded+missing),6),'missing_funding_held_hours':missing,'max_positions':max((x['open_positions'] for x in curve),default=0),'max_open_stop_risk_fraction':round(max((x['open_stop_risk_usd'] for x in curve),default=0)/INITIAL,6),'kill_switch_triggers':kills}
    return metric,trades,curve

def main():
    data=prep()
    for m in data.values():m['atr']=atr5(m['bars']);m['vwap'],m['sd']=vwap_bands(m['bars'])
    results=[];alltr=[];allcurves=[]
    for w,s,e in WINDOWS:
        for stress in (False,True):
            met,tr,curve=run(data,dt_ms(s),dt_ms(e),stress);met['window']=w;results.append(met);alltr += [{**x,'window':w,'stress':stress} for x in tr];allcurves += [{**x,'window':w,'stress':stress} for x in curve]
            print(w,'stress' if stress else 'base',met['net_return_fraction'],'PF',met['profit_factor'],'DD',met['max_drawdown_fraction'],'n',met['trade_count'])
    out=ROOT/'results'/'five_minute_vwap_reversion_screen';out.mkdir(parents=True,exist_ok=True)
    files=sorted((ROOT/'data'/'raw').glob('*_5m.csv'))+sorted((ROOT/'data'/'raw').glob('*_1h.csv'))+sorted((ROOT/'data'/'raw').glob('*_4h.csv'))+sorted((ROOT/'data'/'processed').glob('*_funding_complete_1h.csv'))
    doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'hypothesis':'Temporary 5m price dislocations from local volume-weighted fair value mean-revert more often in non-trending 4h regimes','fixed_parameters':{'rolling_vwap_and_weighted_sd_bars':N,'entry_z':Z_ENTRY,'regime':'confirmed 4h EMA50/EMA200 neutral','stop_atr_5m':2,'target':'signal-bar 48-bar VWAP','time_stop_hours':12,'risk_fraction':RISK,'slots':1},'execution':'signal on closed 5m, entry next 5m open, target fixed using signal bar, stop-first OHLC ambiguity, gap-through stop at 5m open, Kraken hourly funding, taker fee 5bp and spread/slippage 3bp base / 7.5bp stress each side','results':results}
    (out/'metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for name,rows in [('trades.csv',alltr),('equity.csv',allcurves)]:
        with (out/name).open('w',newline='',encoding='utf8') as f:
            fields=list(dict.fromkeys(k for row in rows for k in row));wr=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');wr.writeheader();wr.writerows(rows)
if __name__=='__main__':main()
