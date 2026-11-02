#!/usr/bin/env python3
"""Audit persisted candle/funding CSVs against their manifests."""
import csv, hashlib, json
from pathlib import Path
from src.data_store import INTERVALS, SYMBOLS, validate
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'/'raw'
def main():
    report=[]
    for asset in SYMBOLS:
        for interval,step in INTERVALS.items():
            p=DATA/f'kraken_futures_{asset}_{interval}.csv'; mpath=p.with_suffix(p.suffix+'.manifest.json')
            rows=list(csv.DictReader(p.open(newline='',encoding='utf8'))); meta=json.loads(mpath.read_text(encoding='utf8'))
            digest=hashlib.sha256(p.read_bytes()).hexdigest(); gaps=validate(rows,step,f'{asset} {interval}',allow_gaps=True)
            okay=digest==meta['sha256'] and len(rows)==meta['rows'] and not gaps
            report.append({'file':p.name,'rows':len(rows),'sha256_matches':digest==meta['sha256'],'manifest_rows_match':len(rows)==meta['rows'],'missing_intervals':len(gaps),'status':'PASS' if okay else 'FAIL'})
        p=DATA/f'kraken_futures_{asset}_funding_1h.csv'; mpath=p.with_suffix(p.suffix+'.manifest.json')
        rows=list(csv.DictReader(p.open(newline='',encoding='utf8'))); meta=json.loads(mpath.read_text(encoding='utf8'))
        digest=hashlib.sha256(p.read_bytes()).hexdigest(); ts=[int(x['timestamp_ms']) for x in rows]
        gaps=sum(b-a!=3600_000 for a,b in zip(ts,ts[1:])); okay=digest==meta['sha256'] and len(rows)==meta['rows']
        report.append({'file':p.name,'rows':len(rows),'sha256_matches':digest==meta['sha256'],'manifest_rows_match':len(rows)==meta['rows'],'missing_intervals':gaps,'coverage_fraction':meta.get('coverage_fraction'),'status':'PASS' if okay else 'FAIL'})
        merged=ROOT/'data'/'processed'/f'kraken_futures_{asset}_funding_complete_1h.csv'
        mpath=merged.with_suffix(merged.suffix+'.manifest.json')
        if merged.exists() and mpath.exists():
            rows=list(csv.DictReader(merged.open(newline='',encoding='utf8'))); meta=json.loads(mpath.read_text(encoding='utf8'))
            digest=hashlib.sha256(merged.read_bytes()).hexdigest(); ts=[int(x['timestamp_ms']) for x in rows]
            gaps=sum(max(0,(b-a)//3600_000-1) for a,b in zip(ts,ts[1:])); okay=digest==meta['sha256'] and len(rows)==meta['rows'] and gaps==meta['missing_intervals']
            report.append({'file':merged.name,'rows':len(rows),'sha256_matches':digest==meta['sha256'],'manifest_rows_match':len(rows)==meta['rows'],'missing_intervals':gaps,'coverage_fraction':meta.get('coverage_fraction'),'overlap_values_mismatched':meta.get('overlap_values_mismatched'),'status':'PASS' if okay else 'FAIL'})
    print(json.dumps(report,indent=2))
    if any(x['status']=='FAIL' for x in report): raise SystemExit(1)
if __name__=='__main__': main()
