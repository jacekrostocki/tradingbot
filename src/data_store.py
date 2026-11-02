#!/usr/bin/env python3
"""Download and validate public Kraken Futures perpetual candles and funding analytics."""
from __future__ import annotations
import argparse, concurrent.futures, csv, datetime as dt, hashlib, json, math, os, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "raw"
BASE = "https://futures.kraken.com/api/charts/v1"
SYMBOLS = {"BTC":"PF_XBTUSD", "ETH":"PF_ETHUSD", "SOL":"PF_SOLUSD", "XRP":"PF_XRPUSD"}
INTERVALS = {"5m":300, "1h":3600, "4h":14400, "1d":86400}
FIELDS = ["timestamp_ms","open","high","low","close","volume"]

def epoch(s: str) -> int:
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())

def fetch(url: str, tries: int = 5):
    for attempt in range(tries):
        try:
            req=urllib.request.Request(url, headers={"Accept":"application/json", "User-Agent":"CryptoQuantResearch/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r: return json.load(r)
        except (OSError, ValueError) as exc:
            if attempt == tries-1: raise RuntimeError(f"Request failed: {url}: {exc}") from exc
            time.sleep(min(2**attempt, 12))

def candle_chunk(symbol: str, interval: str, start: int, end: int):
    url=f"{BASE}/trade/{symbol}/{interval}?"+urllib.parse.urlencode({"from":start,"to":end})
    body=fetch(url)
    return body.get("candles", [])

def download_candles(asset: str, interval: str, start: int, end: int):
    symbol=SYMBOLS[asset]; step=INTERVALS[interval]
    # Kraken chart endpoint returns at most 2,000 bars; query disjoint ranges in parallel.
    width=step*1990
    ranges=[]; cur=start
    while cur<=end:
        stop=min(end,cur+width)
        ranges.append((cur,stop)); cur=stop+step
    rows=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(candle_chunk,symbol,interval,a,b) for a,b in ranges]
        for fut in concurrent.futures.as_completed(futures): rows.extend(fut.result())
    out={}
    for x in rows:
        t=int(x["time"]); out[t]={"timestamp_ms":t,"open":x["open"],"high":x["high"],"low":x["low"],"close":x["close"],"volume":x["volume"]}
    return [out[k] for k in sorted(out)]

def funding_chunk(symbol: str, start: int, end: int):
    url=f"{BASE}/analytics/{symbol}/funding?"+urllib.parse.urlencode({"since":start,"to":end,"interval":3600})
    result=fetch(url).get("result",{})
    stamps=result.get("timestamp",[]); data=result.get("data",{}).get("relativeRate",[])
    # Funding analytics is OHLC per bucket; close is used when that bucket settles.
    return [{"timestamp_ms":int(t),"funding_rate":row[3]} for t,row in zip(stamps,data) if len(row)>=4]

def download_funding(asset: str, start: int, end: int):
    # Kraken's dedicated public endpoint returns up to ~1 year of hourly funding
    # history. The charts analytics funding series has shorter retention.
    symbol=SYMBOLS[asset]
    body=fetch("https://futures.kraken.com/derivatives/api/v4/historicalfundingrates?"+urllib.parse.urlencode({"symbol":symbol}))
    if body.get("result")!="success": raise RuntimeError(f"Funding endpoint failed for {symbol}: {body}")
    rows=[]
    for x in body.get("rates",[]):
        t=int(dt.datetime.fromisoformat(x["timestamp"].replace("Z","+00:00")).timestamp()*1000)
        if start*1000<=t<=end*1000: rows.append({"timestamp_ms":t,"funding_rate":x["relativeFundingRate"]})
    out={int(x["timestamp_ms"]):x for x in rows}
    return [out[k] for k in sorted(out)]

def validate(rows, step_s, label, allow_gaps=False):
    if not rows: raise ValueError(f"{label}: empty data")
    ts=[int(x["timestamp_ms"]) for x in rows]
    if ts!=sorted(set(ts)): raise ValueError(f"{label}: duplicate or unsorted timestamps")
    gaps=[(a,b) for a,b in zip(ts,ts[1:]) if b-a != step_s*1000]
    if gaps and not allow_gaps: raise ValueError(f"{label}: {len(gaps)} missing/nonconsecutive bars; first: {gaps[:3]}")
    for x in rows:
        o,h,l,c=[float(x[k]) for k in ("open","high","low","close")]
        v=float(x["volume"])
        if min(o,h,l,c)<=0 or h<max(o,c) or l>min(o,c) or v<0: raise ValueError(f"{label}: invalid candle at {x['timestamp_ms']}")
    return gaps

def save_csv(path, rows, fields):
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n"); w.writeheader(); w.writerows(rows)
    os.replace(tmp,path)

def manifest(path, rows, venue, asset, interval, step_s, gaps):
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    meta={"venue":"Kraken Futures","market":"linear perpetual","asset":asset,"symbol":SYMBOLS[asset],"interval":interval,"rows":len(rows),"first_ms":int(rows[0]["timestamp_ms"]),"last_ms":int(rows[-1]["timestamp_ms"]),"expected_step_seconds":step_s,"missing_intervals":len(gaps),"first_gaps_ms":gaps[:10],"sha256":sha,"downloaded_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(),"endpoint":venue,"notes":"Public chart data; trade OHLCV is not mark/index data. Verify gaps and feed semantics before interpreting backtest."}
    path.with_suffix(path.suffix+".manifest.json").write_text(json.dumps(meta,indent=2),encoding="utf8")
    return meta

def pull(asset, interval, start, end, allow_gaps, update=False):
    path=DATA/f"kraken_futures_{asset}_{interval}.csv"
    existing=[]
    if update and path.exists():
        with path.open(newline='',encoding='utf8') as f: existing=list(csv.DictReader(f))
        old=json.loads(path.with_suffix(path.suffix+".manifest.json").read_text(encoding="utf8"))
        start=max(start,int(old["last_ms"])//1000-INTERVALS[interval])
    step=INTERVALS[interval]; fresh=download_candles(asset,interval,start,end)
    merged={int(x['timestamp_ms']):x for x in existing}
    merged.update({int(x['timestamp_ms']):x for x in fresh})
    rows=[merged[k] for k in sorted(merged) if k+step*1000<=end*1000]
    gaps=validate(rows,step,f"{asset} {interval}",allow_gaps=allow_gaps)
    save_csv(path,rows,FIELDS)
    meta=manifest(path,rows,f"{BASE}/trade/{{symbol}}/{{resolution}}",asset,interval,step,gaps)
    meta.update({"dataset_start_ms":int(rows[0]["timestamp_ms"]),"dataset_end_ms":int(rows[-1]["timestamp_ms"])})
    path.with_suffix(path.suffix+".manifest.json").write_text(json.dumps(meta,indent=2),encoding="utf8")
    return meta

def pull_funding(asset,start,end,allow_gaps,update=False):
    path=DATA/f"kraken_futures_{asset}_funding_1h.csv"
    existing=[]
    if update and path.exists():
        with path.open(newline='',encoding='utf8') as f: existing=list(csv.DictReader(f))
    fresh=download_funding(asset,start,end)
    merged={int(x['timestamp_ms']):x for x in existing}; merged.update({int(x['timestamp_ms']):x for x in fresh})
    rows=[merged[k] for k in sorted(merged)]
    if rows:
        ts=[int(x['timestamp_ms']) for x in rows]
        if ts!=sorted(set(ts)): raise ValueError(f"{asset} funding: duplicate or unsorted timestamps")
        gaps=[(x,y) for x,y in zip(ts,ts[1:]) if y-x!=3600_000]
        if gaps and not allow_gaps: raise ValueError(f"{asset} funding: {len(gaps)} missing intervals; first: {gaps[:3]}")
        if any(not math.isfinite(float(x['funding_rate'])) for x in rows): raise ValueError(f"{asset} funding: invalid rate")
    else: gaps=[(start*1000,end*1000)]
    save_csv(path,rows,["timestamp_ms","funding_rate"])
    if rows:
        meta=manifest(path,rows,"https://futures.kraken.com/derivatives/api/v4/historicalfundingrates",asset,"funding_1h",3600,gaps)
        meta["notes"]="relativeFundingRate hourly rate; Kraken public endpoint returned limited recent history only. Missing hours remain missing and are not assumed to have zero funding."
        expected=max(0,(end-start)//3600+1); meta.update({"requested_start_ms":start*1000,"requested_end_ms":end*1000,"requested_hour_count":expected,"hour_count_covered":len(rows),"coverage_fraction":round(len(rows)/expected,6) if expected else 0,"coverage_limitation":"Kraken public endpoint returned only its retained history; pre-coverage funding is unavailable"})
        path.with_suffix(path.suffix+".manifest.json").write_text(json.dumps(meta,indent=2),encoding="utf8"); return meta
    return {"asset":asset,"rows":0,"warning":"No funding data available for requested period; Kraken public endpoint only retains about one year"}

def main():
    p=argparse.ArgumentParser(); p.add_argument("--assets",nargs="+",default=list(SYMBOLS)); p.add_argument("--intervals",nargs="+",default=list(INTERVALS)); p.add_argument("--start",default="2023-11-02T00:00:00+00:00"); p.add_argument("--end",default=dt.datetime.now(dt.timezone.utc).replace(minute=0,second=0,microsecond=0).isoformat()); p.add_argument("--allow-gaps",action="store_true"); p.add_argument("--skip-funding",action="store_true"); p.add_argument("--update",action="store_true",help="Incrementally refresh existing datasets from the last saved bar"); a=p.parse_args()
    start,end=epoch(a.start),epoch(a.end)
    if end<=start: p.error("--end must be after --start")
    for asset in a.assets:
        for interval in a.intervals: print(json.dumps(pull(asset,interval,start,end,a.allow_gaps,a.update)))
        if not a.skip_funding: print(json.dumps(pull_funding(asset,start,end,a.allow_gaps,a.update)))
if __name__=="__main__": main()
