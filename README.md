# Crypto Quant Research

Research-only repository for Kraken Futures linear perpetual contracts. **LIVE trading and order execution are not implemented.** Initial research equity is fixed at USD 900. The 3% average weekly return is a qualification target, not a promise or guarantee; it is not to be pursued by increasing risk or leverage.

## Data

Download a rolling 3+ year sample (public Kraken Futures trade candles and funding analytics):

```bash
python -m src.data_store --start 2023-11-02T00:00:00+00:00 --end 2026-11-02T12:00:00+00:00 --allow-gaps
```

The downloader writes 16 OHLCV CSVs (BTC, ETH, SOL, XRP × 5m, 1h, 4h, 1d), a recent funding capture, and SHA-256 manifests under `data/raw/`. `--allow-gaps` preserves and counts gaps in the manifest instead of stopping; inspect them before research. Refresh by rerunning with an updated `--end`; overlapping timestamps are deduplicated by the downloader's range assembly. By default the downloader fails on detected gaps. All API calls are public and unauthenticated.

Kraken's chart API timestamps are UTC milliseconds and the request parameters use epoch seconds. `trade` candles reflect executed-trade charts, not mark or index prices. To obtain a longer funding history, run:

```bash
python -m src.merge_funding_history
```

This downloads Kraken's official historical funding export and combines it with the recent public API capture. It writes full `funding_complete_1h.csv` series and manifests under `data/processed/`; the downloaded 110MB archive is ignored by Git. The current captured export reaches 1 Feb 2026; the public API supplies the later tail. All 2,243 overlapping hourly values matched exactly for each of BTC, ETH, SOL and XRP. The merge spans the entire candle history (2 Nov 2023–2 Nov 2026) with eight explicitly recorded missing funding hours per asset; missing values are not filled. Kraken changed from a 4-hour to a 1-hour funding calculation/settlement window on 29 Sep 2022, before this dataset begins. `src.backtest.load()` prefers merged funding when it exists, then falls back to the original raw API capture. `src.audit_data` validates both raw files and merged funding manifests.

## Research

```bash
python -m src.backtest --assets BTC ETH SOL XRP
```

The stdlib-only simulator records experiment metrics and individual trades in `results/`. It starts every simulation at USD 900 and caps notional at 0.75× equity; risk budget is 0.25% per position; one position per asset/experiment; 5 bps taker fee per side, plus 1.5 bps spread and 1.5 bps slippage per side baseline (3.75 bps each in stress); funding is applied from the hourly Kraken series. Strategies are fixed research hypotheses: 4H trend + 1H Donchian, momentum + price structure, breakout + retest, and EMA pullback. Signals use closed bars and next-hour open execution. No leverage is required by the simulator.

The stress scenario changes execution friction, while entry and exit prices use adverse direction. Stop trigger is approximated from OHLC trade bars; this does not model mark-price stop triggers, order book depth, partial fills, liquidation, margin conversion, or stop-market price bands. Treat the backtest as a screening tool, not proof of profitability. Inspect dataset manifests and the cost/funding model before interpreting a result.

Legacy Bybit summaries in `research/legacy_intraday_results.csv` are retained for provenance only. They are not Kraken results and have not been independently reproduced.

## Reproducibility and safety

Experiments save config, code hash, metrics, trade ledger, costs, split indices, and dataset manifests. Do not tune on the final chronological holdout. No API secrets belong in the repository. There is no live trading adapter, key handling, or order placement in this project.
Latest data-audited iteration and limitations: see [`research/ITERATION_REPORT_2026-11-02.md`](research/ITERATION_REPORT_2026-11-02.md) and [`research/ITERATION_2_2026-11-02.md`](research/ITERATION_2_2026-11-02.md). The second report covers the 5m screens, weekly bootstrap analysis, and hybrid trend/mean-reversion test. Reproduce its data audit and core tests with the commands in that report. Current status remains research-only / NO-GO for deployment.
