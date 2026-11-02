#!/usr/bin/env python3
"""Build full hourly Kraken funding histories from the official export + API tail.

The official CSV archive runs through 2026-02-01 in its current downloadable copy.
The existing public API capture supplies the more recent tail. Exact overlap is
checked before merging; missing rows are recorded, never forward-filled.
"""
from __future__ import annotations
import argparse,csv,datetime as dt,hashlib,json,urllib.request,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXPORT_URL='https://assets-cms.kraken.com/files/51n36hrp/facade/4b70936c1227e4ae5514cba8bf41a5561cf13bd7.zip?dl='
SYMBOLS={'BTC':'PF_XBTUSD','ETH':'PF_ETHUSD','SOL':'PF_SOLUSD','XRP':'PF_XRPUSD'}
MS_HOUR=3_600_000
def parse_export(b):
    out={}
    for r in csv.DictReader(b.decode('utf8').splitlines()):
        # Export timestamps are UTC, represented without a zone suffix.
        t=dt.datetime.strptime(r['timestamp'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=dt.timezone.utc)
        out[int(t.timestamp()*1000)]=float(r['relative_rate'])
    return out
def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path);a=p.parse_args()
    archive=a.archive or ROOT/'data'/'processed'/'kraken_historical_funding_export.zip'
    archive.parent.mkdir(parents=True,exist_ok=True)
    if not archive.exists():
        req=urllib.request.Request(EXPORT_URL,headers={'User-Agent':'TradingQuantResearch/1.0'})
        with urllib.request.urlopen(req,timeout=90) as r:archive.write_bytes(r.read())
    archive_sha=hashlib.sha256(archive.read_bytes()).hexdigest();outdir=ROOT/'data'/'processed';outdir.mkdir(exist_ok=True)
    all_meta=[]
    with zipfile.ZipFile(archive) as z:
      for asset,symbol in SYMBOLS.items():
        ex=parse_export(z.read(f'exports/{symbol}.csv'))
        api={int(r['timestamp_ms']):float(r['funding_rate']) for r in csv.DictReader((ROOT/'data'/'raw'/f'kraken_futures_{asset}_funding_1h.csv').open(encoding='utf8'))}
        overlap=set(ex)&set(api);mismatch=[t for t in overlap if abs(ex[t]-api[t])>1e-15]
        if mismatch:raise ValueError(f'{asset}: {len(mismatch)} export/API overlap values differ; sample timestamp {mismatch[0]}')
        merged={**ex,**api};candles=list(csv.DictReader((ROOT/'data'/'raw'/f'kraken_futures_{asset}_1h.csv').open(encoding='utf8')))
        start=int(candles[0]['timestamp_ms']);end=int(candles[-1]['timestamp_ms'])
        vals={t:r for t,r in merged.items() if start<=t<=end};expected=list(range(start,end+1,MS_HOUR));missing=[t for t in expected if t not in vals]
        dest=outdir/f'kraken_futures_{asset}_funding_complete_1h.csv'
        with dest.open('w',newline='',encoding='utf8') as f:
            w=csv.DictWriter(f,fieldnames=('timestamp_ms','funding_rate'),lineterminator='\n');w.writeheader()
            for t in sorted(vals):w.writerow({'timestamp_ms':t,'funding_rate':format(vals[t],'.17g')})
        digest=hashlib.sha256(dest.read_bytes()).hexdigest()
        manifest={'venue':'Kraken Futures','market':'linear perpetual','asset':asset,'symbol':symbol,'interval':'funding_1h','rows':len(vals),'first_ms':min(vals) if vals else None,'last_ms':max(vals) if vals else None,'expected_step_seconds':3600,'missing_intervals':len(missing),'missing_timestamps_ms':missing,'sha256':digest,'sources':[{'type':'official downloadable historical funding export','url':'https://support.kraken.com/articles/export-historical-funding-rates','archive_sha256':archive_sha,'included_through_ms':max(ex)},{'type':'Kraken Futures public historical funding endpoint','endpoint':'https://futures.kraken.com/derivatives/api/v4/historicalfundingrates','current_capture_file':f'data/raw/kraken_futures_{asset}_funding_1h.csv'}],'overlap_rows':len(overlap),'overlap_values_mismatched':len(mismatch),'rate_field':'relative_rate from export / relativeFundingRate from API','funding_period_note':'Data is hourly in candle interval; pre-2022-09-29 Kraken funding events used a 4-hour interval and must not be treated as an hourly per-period rate. The market data tested here begins 2023-11-02.','coverage_fraction':round(len(vals)/max(len(expected),1),8),'candles_start_ms':start,'candles_end_ms':end}
        dest.with_suffix(dest.suffix+'.manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8');all_meta.append(manifest)
        print(asset,'rows',len(vals),'expected',len(expected),'coverage',manifest['coverage_fraction'],'missing',len(missing),'overlap',len(overlap),'exact',not mismatch,'range',manifest['first_ms'],manifest['last_ms'])
    (outdir/'funding_merge_audit.json').write_text(json.dumps({'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'archive_sha256':archive_sha,'assets':all_meta},indent=2),encoding='utf8')
if __name__=='__main__':main()
