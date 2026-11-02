#!/usr/bin/env python3
"""Cross-asset perp funding-spread carry with market-risk stops."""
from __future__ import annotations
import csv,datetime as dt,hashlib,json,math,statistics
from pathlib import Path
from .backtest import load,atr
from .portfolio_momentum import ASSETS,INITIAL,FEE,BASE_FRICTION,STRESS_FRICTION,dt_ms,utc
from .intrabar_execution_screen import WINDOWS
from .portfolio_concurrency import DAILY_STOP,WEEKLY_STOP,DD_STOP

ROOT=Path(__file__).resolve().parents[1];H=3_600_000;D=24*H;RISK=.0025;SPREAD_MIN=.00015

def prep():
    d={}
    for a in ASSETS:
        h1,h4,fund=load(a);d[a]={'bars':h1,'atr':atr(h1),'fund':fund}
    ts=[r['timestamp_ms'] for r in d['BTC']['bars']]
    if any([r['timestamp_ms'] for r in d[a]['bars']]!=ts for a in ASSETS):raise ValueError('1h grids differ')
    return d

def closepos(a,p,b,fr,reason):
    out=b*(1-fr*p['side']);gross=p['side']*(out-p['entry'])*p['qty'];fees=p['qty']*(p['entry']+out)*FEE;net=gross-fees+p['funding']
    p.update(exit=out,gross=gross,fees=fees,net=net,reason=reason)
    return net,p

def run(data,start_ms,end_ms,stress=False):
    ts=[r['timestamp_ms'] for r in data['BTC']['bars']];lo=next(i for i,t in enumerate(ts) if t>=start_ms);hi=next((i for i,t in enumerate(ts) if t>=end_ms),len(ts));fr=STRESS_FRICTION if stress else BASE_FRICTION
    eq=peak=INITIAL;dd=0.;last_mark=INITIAL;day0=week0=INITIAL;dayid=weekid=None;halt=False;pos={};trades=[];curve=[];funded=missing=0;kills={'daily':0,'weekly':0,'drawdown':0}
    for i in range(max(lo,LOOKBACK_START:=24*31),hi):
        t=ts[i];day=t//D;week=(day+3)//7
        if day!=dayid:dayid=day;day0=last_mark
        if week!=weekid:weekid=week;week0=last_mark
        # Funding paid at t belongs to positions held over the preceding hour.
        for a,p in pos.items():
            rate=data[a]['fund'].get(t)
            if rate is None:p['missing_funding_hours']+=1;missing+=1
            else:p['funding']+=-p['side']*rate*p['qty']*p['entry'];funded+=1
        if t%D==0:
            rates={}
            for a,m in data.items():
                xs=[m['fund'].get(t-j*H) for j in range(1,25)]
                if all(x is not None for x in xs):rates[a]=statistics.mean(xs)
            desired=()
            if len(rates)==len(ASSETS):
                low=min(rates,key=rates.get);high=max(rates,key=rates.get)
                if low!=high and rates[high]-rates[low]>=SPREAD_MIN:desired=((low,1),(high,-1))
            current=tuple(sorted((a,p['side']) for a,p in pos.items()));target=tuple(sorted(desired))
            if current!=target:
                for a,p in list(pos.items()):
                    pnl,tr=closepos(a,p,data[a]['bars'][i]['open'],fr,'funding_rebalance');eq+=pnl;tr.update(exit_ms=t,equity=eq);trades.append(tr)
                pos={}
                if target and not halt and eq/day0-1>DAILY_STOP and eq/week0-1>WEEKLY_STOP and eq/peak-1>DD_STOP:
                    for a,side in target:
                        m=data[a];b=m['bars'][i];av=m['atr'][i-1]
                        if not av or av<=0:continue
                        entry=b['open']*(1+fr*side);dist=2*av;rf=dist/entry+2*(FEE+fr);notional=min(eq*.375,eq*(RISK/2)/rf)
                        if notional<10:continue
                        pos[a]={'asset':a,'strategy':'cross_asset_funding_spread_carry','side':side,'signal_ms':ts[i-1],'entry_ms':t,'entry':entry,'qty':notional/entry,'notional':notional,'stop':entry-side*dist,'funding':0.,'missing_funding_hours':0,'funding_rate_24h':rates[a]}
        else:
            for a,p in list(pos.items()):
                b=data[a]['bars'][i];side=p['side'];hit=b['low']<=p['stop'] if side==1 else b['high']>=p['stop']
                if hit:
                    px=min(p['stop'],b['open']) if side==1 else max(p['stop'],b['open']);pnl,tr=closepos(a,p,px,fr,'stop_1h');eq+=pnl;tr.update(exit_ms=t,equity=eq);trades.append(tr);del pos[a]
        mark=eq
        for a,p in pos.items():
            b=data[a]['bars'][i];ad=b['low'] if p['side']==1 else b['high'];mark+=p['side']*(ad-p['entry'])*p['qty']-p['qty']*(p['entry']+ad)*FEE+p['funding']
        peak=max(peak,mark);dd=min(dd,mark/peak-1);kill=None
        if mark/peak-1<=DD_STOP:halt=True
        if pos:
            if mark/peak-1<=DD_STOP:kill='drawdown'
            elif mark/day0-1<=DAILY_STOP:kill='daily'
            elif mark/week0-1<=WEEKLY_STOP:kill='weekly'
        if kill:
            for a,p in list(pos.items()):
                b=data[a]['bars'][i];ad=b['low'] if p['side']==1 else b['high'];pnl,tr=closepos(a,p,ad,fr,f'{kill}_kill_switch');eq+=pnl;tr.update(exit_ms=t,equity=eq);trades.append(tr);kills[kill]+=1
            pos={};mark=eq
        if t%H==0:
            risk=sum(max(0,p['side']*(p['entry']-p['stop'])*p['qty'])+p['notional']*2*(FEE+fr) for p in pos.values())
            curve.append({'timestamp_ms':t,'equity_usd':eq,'adverse_mark_equity_usd':mark,'open_positions':len(pos),'open_stop_risk_usd':risk})
        last_mark=mark
    if pos:
        i=hi-1;t=ts[i]
        for a,p in list(pos.items()):
            pnl,tr=closepos(a,p,data[a]['bars'][i]['close'],fr,'period_end');eq+=pnl;tr.update(exit_ms=t,equity=eq);trades.append(tr)
    wins=[p['net'] for p in trades if p['net']>0];loss=[p['net'] for p in trades if p['net']<=0];pf=sum(wins)/abs(sum(loss)) if loss and sum(loss) else 0
    metric={'stress':stress,'window_start_utc':utc(ts[lo]),'window_end_utc':utc(ts[hi-1]),'final_equity_usd':round(eq,4),'net_return_fraction':round(eq/INITIAL-1,6),'trade_count':len(trades),'expectancy_usd':round(statistics.mean([p['net'] for p in trades]),5) if trades else 0,'profit_factor':round(pf,4),'win_rate':round(len(wins)/len(trades),4) if trades else 0,'max_drawdown_fraction':round(dd,6),'fees_usd':round(sum(p.get('fees',0) for p in trades),4),'funding_usd':round(sum(p['funding'] for p in trades),4),'funding_coverage_fraction':round(funded/max(1,funded+missing),6),'max_positions':max((x['open_positions'] for x in curve),default=0),'max_open_stop_risk_fraction':round(max((x['open_stop_risk_usd'] for x in curve),default=0)/INITIAL,6),'kill_switch_triggers':kills}
    return metric,trades,curve

def main():
    data=prep();results=[];trades=[];curves=[]
    for w,s,e in WINDOWS:
        for stress in (False,True):
            met,tr,eq=run(data,dt_ms(s),dt_ms(e),stress);met['window']=w;results.append(met);trades += [{**x,'window':w,'stress':stress} for x in tr];curves += [{**x,'window':w,'stress':stress} for x in eq]
            print(w,'stress' if stress else 'base',met['net_return_fraction'],'PF',met['profit_factor'],'DD',met['max_drawdown_fraction'],'n',met['trade_count'])
    out=ROOT/'results'/'funding_carry_spread_screen';out.mkdir(parents=True,exist_ok=True)
    files=sorted((ROOT/'data'/'raw').glob('*_1h.csv'))+sorted((ROOT/'data'/'processed').glob('*_funding_complete_1h.csv'))
    doc={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'hypothesis':'Short the highest 24h-mean hourly funding asset and buy the lowest; funding spread is a carry signal, not a directional price forecast','fixed_parameters':{'funding_window_hours':24,'minimum_spread_per_hour':SPREAD_MIN,'minimum_spread_bp_per_hour':SPREAD_MIN*10000,'rebalance':'daily UTC; maintain same legs between rebalances','stop_atr_1h':2,'risk_per_leg_fraction':RISK/2,'total_open_stop_risk_fraction':RISK,'gross_notional_cap_fraction':.75},'execution':'prior 24 completed hourly funding observations required; entry/exit at next UTC-day 1h open; stop-first hourly OHLC and gap-through at bar open; 5bp taker fees, 3bp base or 7.5bp stress spread/slippage each side; Kraken hourly funding','results':results}
    (out/'metrics.json').write_text(json.dumps(doc,indent=2),encoding='utf8')
    for name,rows in [('trades.csv',trades),('equity.csv',curves)]:
        with (out/name).open('w',newline='',encoding='utf8') as f:
            fields=list(dict.fromkeys(k for row in rows for k in row));wr=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');wr.writeheader();wr.writerows(rows)
if __name__=='__main__':main()
