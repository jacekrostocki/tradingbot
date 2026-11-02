#!/usr/bin/env python3
"""Combine 1h breakout continuation in trending 4h regimes and 5m VWAP reversion in neutral regimes."""
from __future__ import annotations
import bisect,csv,datetime as dt,hashlib,json,math,statistics
from pathlib import Path
from .backtest import signals
from .five_minute_donchian_screen import prep,atr5
from .five_minute_vwap_reversion_screen import vwap_bands,N
from .intrabar_execution_screen import WINDOWS,HOUR,BAR5
from .portfolio_momentum import ASSETS,INITIAL,FEE,BASE_FRICTION,STRESS_FRICTION,RISK,NOTIONAL_CAP,MOMENTUM_LOOKBACK,dt_ms,utc
from .portfolio_concurrency import DAILY_STOP,WEEKLY_STOP,DD_STOP

ROOT=Path(__file__).resolve().parents[1];MAX_TREND_HOLD=72*HOUR;MAX_MR_HOLD=12*HOUR;Z=2.0

def build():
    d=prep()
    for a,m in d.items():
        h1,atr1,tr1,sig1,fund=signals(a,'breakout_retest')
        m.update({'atr1h':atr1,'trend1h':tr1,'sig1h':sig1,'fund':fund,'h1ts':[x['timestamp_ms'] for x in h1],'vwap':None})
        m['vwap'],m['sd']=vwap_bands(m['bars'])
    return d

def run(data,start_ms,end_ms,stress=False):
    ts=[x['timestamp_ms'] for x in data['BTC']['bars']];lo=bisect.bisect_left(ts,start_ms);hi=bisect.bisect_left(ts,end_ms);fr=STRESS_FRICTION if stress else BASE_FRICTION
    eq=peak=INITIAL;dd=0.;last_mark=INITIAL;day0=week0=INITIAL;dayid=weekid=None;halt=False;pos=None;trades=[];curve=[];funded=missing=0;kills={'daily':0,'weekly':0,'drawdown':0}
    for k in range(lo,hi):
        t=ts[k];day=t//86_400_000;week=(day+3)//7
        if day!=dayid:dayid=day;day0=last_mark
        if week!=weekid:weekid=week;week0=last_mark
        new_entry=False
        if pos is None and not halt and eq/day0-1>DAILY_STOP and eq/week0-1>WEEKLY_STOP and eq/peak-1>DD_STOP and k>lo:
            candidates=[]
            for a,m in data.items():
                i=k-1
                if not m['trend_ready'][k]:continue
                # Use regime known at the current 5m open; 4h bars close on boundary timestamps.
                regime=m['trend'][k]
                if regime:
                    if t%HOUR:continue
                    j=bisect.bisect_left(m['h1ts'],t)-1
                    if j<max(MOMENTUM_LOOKBACK,201) or m['h1ts'][j]+HOUR!=t:continue
                    side=m['sig1h'][j]
                    if side!=regime or not m['atr1h'][j]:continue
                    momentum=side*(float(m['h1'][j]['close'])/float(m['h1'][j-MOMENTUM_LOOKBACK]['close'])-1)
                    if momentum>0:candidates.append((2+momentum,'trend',a,side,i,j,momentum))
                else:
                    vw=m['vwap'][i];sd=m['sd'][i];b=m['bars'][i]
                    if not vw or not sd or sd<=0:continue
                    z=(b['close']-vw)/sd;side=-1 if z>=Z else (1 if z<=-Z else 0)
                    if side:candidates.append((abs(z),'vwap',a,side,i,None,z))
            if candidates:
                _,kind,a,side,i,j,score=max(candidates);m=data[a];b=m['bars'][k];entry=b['open']*(1+fr*side)
                if kind=='trend':dist=2*m['atr1h'][j];target=None
                else:dist=2*m['atr'][i];target=m['vwap'][i]
                if dist>0 and (target is None or side*(target-entry)>entry*2*(FEE+fr)):
                    rf=dist/entry+2*(FEE+fr);notional=min(eq*NOTIONAL_CAP,eq*RISK/rf)
                    if notional>=10:
                        pos={'asset':a,'strategy':f'hybrid_{kind}_shared_risk','kind':kind,'side':side,'signal_ms':ts[i],'entry_ms':t,'entry':entry,'target':target,'qty':notional/entry,'notional':notional,'stop':entry-side*dist,'risk_dist':dist,'extreme':entry,'trail_active':False,'funding':0.,'missing_funding_hours':0,'score':score};new_entry=True
        if pos is not None:
            m=data[pos['asset']];b=m['bars'][k];side=pos['side']
            if t%HOUR==0 and not new_entry:
                rate=m['fund'].get(t)
                if rate is None:pos['missing_funding_hours']+=1;missing+=1
                else:pos['funding']+=-side*rate*pos['qty']*pos['entry'];funded+=1
            stop_hit=b['low']<=pos['stop'] if side==1 else b['high']>=pos['stop'];px=None;reason=''
            if stop_hit:px=min(pos['stop'],b['open']) if side==1 else max(pos['stop'],b['open']);reason='stop_first'
            elif pos['kind']=='trend':
                hidx=bisect.bisect_right(m['h1ts'],t)-1
                if m['trend1h'][hidx]==-side:px=b['open'];reason='4h_trend_flip'
                elif t-pos['entry_ms']>=MAX_TREND_HOLD:px=b['open'];reason='time_stop_72h'
                else:
                    fav=b['high']-pos['entry'] if side==1 else pos['entry']-b['low']
                    if fav>=pos['risk_dist']:pos['trail_active']=True
                    atridx=max(0,hidx-1);atr=m['atr1h'][atridx]
                    if pos['trail_active'] and atr:
                        cand=pos['extreme']-3*atr if side==1 else pos['extreme']+3*atr
                        pos['stop']=max(pos['stop'],cand) if side==1 else min(pos['stop'],cand)
                    pos['extreme']=max(pos['extreme'],b['high']) if side==1 else min(pos['extreme'],b['low'])
            else:
                target_hit=b['high']>=pos['target'] if side==1 else b['low']<=pos['target']
                if target_hit:px=pos['target'];reason='vwap_target'
                elif t-pos['entry_ms']>=MAX_MR_HOLD:px=b['open'];reason='time_stop_12h'
            if px is None and k==hi-1:px=b['close'];reason='period_end'
            if px is not None:
                out=px*(1-fr*side);gross=side*(out-pos['entry'])*pos['qty'];fees=pos['qty']*(pos['entry']+out)*FEE;net=gross-fees+pos['funding'];eq+=net;pos.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason=reason,equity=eq);trades.append(pos);pos=None
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
            p=pos;b=data[p['asset']]['bars'][k];side=p['side'];ad=b['low'] if side==1 else b['high'];out=ad*(1-fr*side);gross=side*(out-p['entry'])*p['qty'];fees=p['qty']*(p['entry']+out)*FEE;net=gross-fees+p['funding'];eq+=net;p.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason=f'{kill}_kill_switch',equity=eq);trades.append(p);pos=None;kills[kill]+=1;mark=eq
        if t%HOUR==0 or k==hi-1:
            risk=max(0,pos['side']*(pos['entry']-pos['stop'])*pos['qty'])+pos['notional']*2*(FEE+fr) if pos else 0
            curve.append({'timestamp_ms':t,'equity_usd':eq,'adverse_mark_equity_usd':mark,'open_positions':int(pos is not None),'open_stop_risk_usd':risk})
        last_mark=mark
    wins=[x['net'] for x in trades if x['net']>0];loss=[x['net'] for x in trades if x['net']<=0];pf=sum(wins)/abs(sum(loss)) if loss and sum(loss) else 0
    met={'stress':stress,'window_start_utc':utc(ts[lo]),'window_end_utc':utc(ts[hi-1]),'initial_equity_usd':INITIAL,'final_equity_usd':round(eq,4),'net_return_fraction':round(eq/INITIAL-1,6),'trade_count':len(trades),'expectancy_per_trade_usd':round(statistics.mean([x['net'] for x in trades]),6) if trades else 0,'profit_factor':round(pf,4),'win_rate':round(len(wins)/len(trades),4) if trades else 0,'max_drawdown_fraction':round(dd,6),'fees_usd':round(sum(x['fees'] for x in trades),4),'funding_usd':round(sum(x['funding'] for x in trades),4),'funding_coverage_fraction':round(funded/max(1,funded+missing),6),'max_positions':max((x['open_positions'] for x in curve),default=0),'max_open_stop_risk_fraction':round(max((x['open_stop_risk_usd'] for x in curve),default=0)/INITIAL,6),'kill_switch_triggers':kills,'trend_trade_count':sum(x['kind']=='trend' for x in trades),'vwap_trade_count':sum(x['kind']=='vwap' for x in trades)}
    return met,trades,curve

def main():
    data=build();results=[];trades=[];curves=[]
    for w,s,e in WINDOWS:
        for stress in (False,True):
            met,tr,curve=run(data,dt_ms(s),dt_ms(e),stress);met['window']=w;results.append(met);trades += [{**x,'window':w,'stress':stress} for x in tr];curves += [{**x,'window':w,'stress':stress} for x in curve]
            print(w,'stress' if stress else 'base',met['net_return_fraction'],'PF',met['profit_factor'],'DD',met['max_drawdown_fraction'],'n',met['trade_count'],'trend/MR',met['trend_trade_count'],met['vwap_trade_count'])
    out=ROOT/'results'/'hybrid_regime_screen';out.mkdir(parents=True,exist_ok=True)
    files=sorted((ROOT/'data'/'raw').glob('*_5m.csv'))+sorted((ROOT/'data'/'raw').glob('*_1h.csv'))+sorted((ROOT/'data'/'raw').glob('*_4h.csv'))+sorted((ROOT/'data'/'processed').glob('*_funding_complete_1h.csv'))
    doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'hypothesis':'Breakout-retest continuation is active only in confirmed 4h trend; VWAP mean-reversion is active only in confirmed neutral 4h regime. Both share one position and the same 0.25% stop-risk budget.','fixed_parameters':{'trend_signal':'1h breakout-retest, 4h EMA50/200 regime, 30d momentum rank','trend_stop':'2x 1h ATR; trail 3x 1h ATR after +1R; time stop 72h','mean_reversion_signal':'48-bar 5m volume-weighted VWAP, 2 weighted SD threshold; neutral 4h regime','mean_reversion_exit':'signal VWAP target; 2x 5m ATR stop, 12h time stop','risk_fraction_total':RISK,'positions':1},'execution':'5m next-open entries, stop-first intrabar, gap-through fills at 5m open, Kraken hourly funding, taker fee 5bp and spread/slippage 3bp base / 7.5bp stress each side','results':results}
    (out/'metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for name,rows in [('trades.csv',trades),('equity.csv',curves)]:
        with (out/name).open('w',newline='',encoding='utf8') as f:
            fields=list(dict.fromkeys(k for row in rows for k in row));wr=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');wr.writeheader();wr.writerows(rows)
if __name__=='__main__':main()
