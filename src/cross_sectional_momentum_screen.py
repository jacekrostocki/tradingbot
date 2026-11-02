#!/usr/bin/env python3
"""Weekly/daily 30d cross-sectional long-short momentum, shared risk budget."""
from __future__ import annotations
import csv,datetime as dt,hashlib,json,math,statistics
from pathlib import Path
from .backtest import load,atr
from .portfolio_momentum import ASSETS,INITIAL,FEE,BASE_FRICTION,STRESS_FRICTION,dt_ms,utc
from .intrabar_execution_screen import WINDOWS
from .portfolio_concurrency import DAILY_STOP,WEEKLY_STOP,DD_STOP

ROOT=Path(__file__).resolve().parents[1];H=3_600_000;D=24*H;LOOKBACK=24*30;SKIP=24;RISK=.0025

def prep():
    d={}
    for a in ASSETS:
        h1,h4,fund=load(a);d[a]={'bars':h1,'atr':atr(h1),'fund':fund}
    ts=[r['timestamp_ms'] for r in d['BTC']['bars']]
    if any([r['timestamp_ms'] for r in d[a]['bars']]!=ts for a in ASSETS):raise ValueError('1h grids differ')
    return d

def run(data,start_ms,end_ms,stress=False,slots_each_side=1):
    ts=[r['timestamp_ms'] for r in data['BTC']['bars']];lo=next(i for i,t in enumerate(ts) if t>=start_ms);hi=next((i for i,t in enumerate(ts) if t>=end_ms),len(ts));fr=STRESS_FRICTION if stress else BASE_FRICTION
    eq=peak=INITIAL;dd=0.;last_mark=INITIAL;day0=week0=INITIAL;dayid=weekid=None;halt=False;positions={};trades=[];curve=[];funded=missing=0;kills={'daily':0,'weekly':0,'drawdown':0}
    for i in range(max(lo,LOOKBACK+SKIP+1),hi):
        t=ts[i];day=t//D;week=(day+3)//7
        if day!=dayid:dayid=day;day0=last_mark
        if week!=weekid:weekid=week;week0=last_mark
        rebalance=t%D==0
        # Carry funding through the completed hour for positions held at its boundary.
        for a,p in list(positions.items()):
            rate=data[a]['fund'].get(t)
            if rate is None:p['missing_funding_hours']+=1;missing+=1
            else:p['funding']+=-p['side']*rate*p['qty']*p['entry'];funded+=1
        # Rebalance at UTC midnight. The ranking uses only closes known at t.
        if rebalance:
            for a,p in list(positions.items()):
                b=data[a]['bars'][i];out=b['open']*(1-fr*p['side']);gross=p['side']*(out-p['entry'])*p['qty'];fees=p['qty']*(p['entry']+out)*FEE;net=gross-fees+p['funding'];eq+=net;p.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason='daily_rebalance',equity=eq);trades.append(p)
            positions={}
            if i>=LOOKBACK+SKIP and not halt and eq/day0-1>DAILY_STOP and eq/week0-1>WEEKLY_STOP and eq/peak-1>DD_STOP:
                scores=[]
                for a,m in data.items():
                    c0=float(m['bars'][i-SKIP-1]['close']);c1=float(m['bars'][i-SKIP-LOOKBACK-1]['close']);scores.append((c0/c1-1,a))
                scores.sort();shorts=[a for _,a in scores[:slots_each_side]];longs=[a for _,a in scores[-slots_each_side:]]
                n=2*slots_each_side;per_risk=RISK/n;per_cap=.75/n
                for side,assets in ((-1,shorts),(1,longs)):
                    for a in assets:
                        m=data[a];b=m['bars'][i];atr_prev=m['atr'][i-1]
                        if not atr_prev or atr_prev<=0:continue
                        entry=b['open']*(1+fr*side);dist=2*atr_prev;riskfrac=dist/entry+2*(FEE+fr);notional=min(eq*per_cap,eq*per_risk/riskfrac)
                        if notional<10:continue
                        positions[a]={'asset':a,'strategy':f'cross_sectional_30d_skip1d_{slots_each_side}L{slots_each_side}S','side':side,'signal_ms':ts[i-1],'entry_ms':t,'entry':entry,'qty':notional/entry,'notional':notional,'stop':entry-side*dist,'funding':0.,'missing_funding_hours':0}
        else:
            # Apply stop-first intrabar execution for positions between rebalances.
            for a,p in list(positions.items()):
                b=data[a]['bars'][i];side=p['side'];hit=b['low']<=p['stop'] if side==1 else b['high']>=p['stop']
                if hit:
                    px=min(p['stop'],b['open']) if side==1 else max(p['stop'],b['open']);out=px*(1-fr*side);gross=side*(out-p['entry'])*p['qty'];fees=p['qty']*(p['entry']+out)*FEE;net=gross-fees+p['funding'];eq+=net;p.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason='stop_1h',equity=eq);trades.append(p);del positions[a]
        # Conservative portfolio mark uses adverse hourly extremes and estimated close costs.
        mark=eq
        for a,p in positions.items():
            b=data[a]['bars'][i];ad=b['low'] if p['side']==1 else b['high'];mark+=p['side']*(ad-p['entry'])*p['qty']-p['qty']*(p['entry']+ad)*FEE+p['funding']
        peak=max(peak,mark);dd=min(dd,mark/peak-1)
        kill=None
        if mark/peak-1<=DD_STOP:halt=True
        if positions:
            if mark/peak-1<=DD_STOP:kill='drawdown'
            elif mark/day0-1<=DAILY_STOP:kill='daily'
            elif mark/week0-1<=WEEKLY_STOP:kill='weekly'
        if kill:
            for a,p in list(positions.items()):
                b=data[a]['bars'][i];side=p['side'];ad=b['low'] if side==1 else b['high'];out=ad*(1-fr*side);gross=side*(out-p['entry'])*p['qty'];fees=p['qty']*(p['entry']+out)*FEE;net=gross-fees+p['funding'];eq+=net;p.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason=f'{kill}_kill_switch',equity=eq);trades.append(p);kills[kill]+=1
            positions={};mark=eq
        if t%H==0:
            risk=sum(max(0,p['side']*(p['entry']-p['stop'])*p['qty'])+p['notional']*2*(FEE+fr) for p in positions.values())
            curve.append({'timestamp_ms':t,'equity_usd':eq,'adverse_mark_equity_usd':mark,'open_positions':len(positions),'open_stop_risk_usd':risk})
        last_mark=mark
    if positions:
        i=hi-1;t=ts[i]
        for a,p in list(positions.items()):
            b=data[a]['bars'][i];side=p['side'];out=b['close']*(1-fr*side);gross=side*(out-p['entry'])*p['qty'];fees=p['qty']*(p['entry']+out)*FEE;net=gross-fees+p['funding'];eq+=net;p.update(exit_ms=t,exit=out,gross=gross,fees=fees,net=net,reason='period_end',equity=eq);trades.append(p)
    wins=[p['net'] for p in trades if p['net']>0];loss=[p['net'] for p in trades if p['net']<=0];pf=sum(wins)/abs(sum(loss)) if loss and sum(loss) else 0
    metric={'stress':stress,'slots_each_side':slots_each_side,'window_start_utc':utc(ts[lo]),'window_end_utc':utc(ts[hi-1]),'final_equity_usd':round(eq,4),'net_return_fraction':round(eq/INITIAL-1,6),'trade_count':len(trades),'expectancy_usd':round(statistics.mean([p['net'] for p in trades]),5) if trades else 0,'profit_factor':round(pf,4),'win_rate':round(len(wins)/len(trades),4) if trades else 0,'max_drawdown_fraction':round(dd,6),'fees_usd':round(sum(p.get('fees',0) for p in trades),4),'funding_usd':round(sum(p['funding'] for p in trades),4),'funding_coverage_fraction':round(funded/max(1,funded+missing),6),'max_positions':max((x['open_positions'] for x in curve),default=0),'max_open_stop_risk_fraction':round(max((x['open_stop_risk_usd'] for x in curve),default=0)/INITIAL,6),'kill_switch_triggers':kills}
    return metric,trades,curve

def main():
    data=prep();results=[];trades=[];curves=[]
    for w,s,e in WINDOWS:
      for slots in (1,2):
       for stress in (False,True):
        met,tr,eq=run(data,dt_ms(s),dt_ms(e),stress,slots);met['window']=w;results.append(met);trades += [{**x,'window':w,'stress':stress} for x in tr];curves += [{**x,'window':w,'slots_each_side':slots,'stress':stress} for x in eq]
        print(w,'L/S',slots,'stress' if stress else 'base',met['net_return_fraction'],'PF',met['profit_factor'],'DD',met['max_drawdown_fraction'],'n',met['trade_count'])
    out=ROOT/'results'/'cross_sectional_momentum_screen';out.mkdir(parents=True,exist_ok=True)
    files=sorted((ROOT/'data'/'raw').glob('*_1h.csv'))+sorted((ROOT/'data'/'processed').glob('*_funding_complete_1h.csv'))
    doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'hypothesis':'30d cross-sectional crypto momentum with a one-day skip; long strongest, short weakest, rebalance daily','fixed_parameters':{'lookback_hours':LOOKBACK,'skip_recent_hours':SKIP,'stop_atr_1h':2,'rebalance':'daily UTC','slots_each_side':[1,2],'total_stop_risk_fraction':RISK,'max_total_gross_notional_fraction':.75},'execution':'signal at UTC midnight from prior completed bars, entry/exit at current 1h open; stop-first hourly OHLC, gap-through fill at bar open; Kraken hourly funding; taker fee 5bp and spread/slippage 3bp base / 7.5bp stress each side','results':results}
    (out/'metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for name,rows in [('trades.csv',trades),('equity.csv',curves)]:
        with (out/name).open('w',newline='',encoding='utf8') as f:
            fields=list(dict.fromkeys(k for row in rows for k in row));wr=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');wr.writeheader();wr.writerows(rows)
if __name__=='__main__':main()
