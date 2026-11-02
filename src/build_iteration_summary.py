#!/usr/bin/env python3
"""Join representative final-window metrics with weekly return summaries."""
import csv,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SELECTIONS=[
 ('1h breakout/retest executed at 5m','intrabar_execution_screen',{}),
 ('Breakout/retest with lower retest volume','volume_confirmation_screen',{'filter':'retest_volume_below_breakout'}),
 ('5m Donchian continuation','five_minute_donchian_screen',{}),
 ('5m VWAP reversion','five_minute_vwap_reversion_screen',{}),
 ('Trend + VWAP regime hybrid','hybrid_regime_screen',{}),
 ('30d cross-sectional momentum, 1 long + 1 short','cross_sectional_momentum_screen',{'slots_each_side':1}),
 ('Funding-extreme contrarian','funding_extremes_screen',{'strategy':'funding_extreme_contrarian_trend_confirmed'}),
 ('30d relative strength vs BTC filter','cross_asset_screen',{'filter':'relative_strength_vs_btc_30d'}),
]
def read(path):
 with path.open(newline='',encoding='utf8') as f:return list(csv.DictReader(f))
def main():
 weekly=read(ROOT/'results'/'iteration_2_weekly_summary.csv');out=[]
 for label,folder,keys in SELECTIONS:
  doc=json.loads((ROOT/'results'/folder/'metrics.json').read_text(encoding='utf8'))
  for m in doc.get('results',[]):
   if m.get('window')!='final_holdout_screened' or m.get('stress') not in (False,'False'):continue
   if any(str(m.get(k))!=str(v) for k,v in keys.items()):continue
   wkey={'source_file':f'results/{folder}/equity.csv','window':'final_holdout_screened','stress':'False',**{k:str(v) for k,v in keys.items()}}
   wr=next((r for r in weekly if all(r.get(k)==v for k,v in wkey.items())),{})
   out.append({'hypothesis':label,'net_profit_usd':m.get('net_pnl_usd',round(float(m['final_equity_usd'])-900,4)),'mean_weekly_return':wr.get('mean_weekly_return'),'median_weekly_return':wr.get('median_weekly_return'),'positive_week_fraction':wr.get('positive_week_fraction'),'worst_week_return':wr.get('worst_week_return'),'weekly_mean_ci_2_5':wr.get('block_bootstrap_mean_ci_2_5'),'weekly_mean_ci_97_5':wr.get('block_bootstrap_mean_ci_97_5'),'sharpe_weekly_annualized':wr.get('sharpe_weekly_annualized'),'sortino_weekly_annualized':wr.get('sortino_weekly_annualized'),'max_drawdown_fraction':m['max_drawdown_fraction'],'profit_factor':m['profit_factor'],'win_rate':m.get('win_rate'),'expectancy_usd':m.get('expectancy_per_trade_usd',m.get('expectancy_usd')),'trade_count':m['trade_count'],'stress':False})
   stress=next((x for x in doc['results'] if x.get('window')=='final_holdout_screened' and x.get('stress') in (True,'True') and all(str(x.get(k))==str(v) for k,v in keys.items())),None)
   if stress:
    wkey['stress']='True';sw=next((r for r in weekly if all(r.get(k)==v for k,v in wkey.items())),{})
    out.append({'hypothesis':label,'net_profit_usd':stress.get('net_pnl_usd',round(float(stress['final_equity_usd'])-900,4)),'mean_weekly_return':sw.get('mean_weekly_return'),'median_weekly_return':sw.get('median_weekly_return'),'positive_week_fraction':sw.get('positive_week_fraction'),'worst_week_return':sw.get('worst_week_return'),'weekly_mean_ci_2_5':sw.get('block_bootstrap_mean_ci_2_5'),'weekly_mean_ci_97_5':sw.get('block_bootstrap_mean_ci_97_5'),'sharpe_weekly_annualized':sw.get('sharpe_weekly_annualized'),'sortino_weekly_annualized':sw.get('sortino_weekly_annualized'),'max_drawdown_fraction':stress['max_drawdown_fraction'],'profit_factor':stress['profit_factor'],'win_rate':stress.get('win_rate'),'expectancy_usd':stress.get('expectancy_per_trade_usd',stress.get('expectancy_usd')),'trade_count':stress['trade_count'],'stress':True})
 p=ROOT/'results'/'iteration_2_candidate_metrics.csv';p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',newline='',encoding='utf8') as f:
  fields=list(out[0]);w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(out)
 print(f'wrote {len(out)} rows to {p.relative_to(ROOT)}')
if __name__=='__main__':main()
