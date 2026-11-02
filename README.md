# Crypto Quant Research

Research-only repository for Kraken Futures linear perpetual contracts. **LIVE trading and order execution are not implemented.** Initial research equity is fixed at USD 900. Historical performance is not a promise of future returns; the 10% weekly/monthly aspiration is not a test objective or guarantee.

## Data

Download a rolling 3+ year sample (public Kraken Futures trade candles and funding analytics):

```bash
python -m src.data_store --start 2023-11-02T00:00:00+00:00 --end 2026-11-02T12:00:00+00:00 --allow-gaps
```

The downloader writes 12 OHLCV CSVs (BTC, ETH, SOL, XRP × 1h, 4h, 1d), four hourly funding CSVs, and SHA-256 manifests under `data/raw/`. `--allow-gaps` preserves and counts gaps in the manifest instead of stopping; inspect them before research. Refresh by rerunning with an updated `--end`; overlapping timestamps are deduplicated by the downloader's range assembly. By default the downloader fails on detected gaps. All API calls are public and unauthenticated.

Kraken's chart API timestamps are UTC milliseconds and the request parameters use epoch seconds. `trade` candles reflect executed-trade charts, not mark or index prices. Funding uses the public historical funding-rate endpoint's `relativeFundingRate` field. Kraken returned only recent funding history (about one year) with a handful of missing hours, so the older part of the three-year price archive is unfunded in the data. Experiments report coverage; only fully covered windows can be interpreted as net of funding. Gaps, contract history, rate field semantics, and incomplete current bars need review before treating results as execution-representative.

## Research

```bash
python -m src.backtest --assets BTC ETH SOL XRP
```

The stdlib-only simulator records experiment metrics and individual trades in `results/`. It starts every simulation at USD 900 and caps notional at 0.75× equity; risk budget is 0.25% per position; one position per asset/experiment; 5 bps taker fee per side, plus 1.5 bps spread and 1.5 bps slippage per side baseline (3.75 bps each in stress); funding is applied from the hourly Kraken series. Strategies are fixed research hypotheses: 4H trend + 1H Donchian, momentum + price structure, breakout + retest, and EMA pullback. Signals use closed bars and next-hour open execution. No leverage is required by the simulator.

The stress scenario changes execution friction, while entry and exit prices use adverse direction. Stop trigger is approximated from OHLC trade bars; this does not model mark-price stop triggers, order book depth, partial fills, liquidation, margin conversion, or stop-market price bands. Treat the backtest as a screening tool, not proof of profitability. Inspect dataset manifests and the cost/funding model before interpreting a result.

Legacy Bybit summaries in `research/legacy_intraday_results.csv` are retained for provenance only. They are not Kraken results and have not been independently reproduced.

## Reproducibility and safety

Experiments save config, code hash, metrics, trade ledger, costs, split indices, and dataset manifests. Do not tune on the final chronological holdout. No API secrets belong in the repository. There is no live trading adapter, key handling, or order placement in this project.
