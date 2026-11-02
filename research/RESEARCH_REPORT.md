# Crypto Quant Research — current snapshot

**Date:** 2026-11-02 UTC  
**Status:** research only; no strategy approved for live trading. No live orders were sent.

## What was carried forward

The linked Bybit conversation reports that weekly multi-asset Momentum 14/30/60 returned **+1.15%** on USD 500 from Dec 2024 to Oct 2026, with 88 trades, PF 1.22 and 1.07% daily-equity drawdown. It explicitly lacked actual historical funding, was exploratory rather than an independent audit, and ETH contributed nearly all profit. The prior conclusion was to treat momentum as a market filter, not a proven standalone strategy, then test structural entries. The new work keeps that warning. It does not combine that Bybit result with Kraken results.

## Data captured

- Kraken Futures linear perpetual trade candles for BTC (`PF_XBTUSD`), ETH (`PF_ETHUSD`), SOL (`PF_SOLUSD`) and XRP (`PF_XRPUSD`).
- 1h, 4h and 1d candles from 2023-11-02 through the latest fully closed candle on 2026-11-02.
- 12 candle files × 4 assets. Each has 26,316 hourly rows, 6,579 four-hour rows, and 1,096 daily rows. No timestamp gaps were found in candle series; hashes and manifests match.
- Hourly funding rates from Kraken's public historical funding endpoint: 8,830 rows per asset, covering only 33.55% of the full candle window. The retained start is 2025-10-30; five hourly gaps occur per asset. The missing prehistory is not assumed to have zero cost. The final holdout (2026-05-22 to 2026-11-02) has full funding coverage.
- Audit: `src.audit_data` checked 16 files; all CSV hashes and manifest row counts matched. It found the five known funding gaps for each asset and no candle gaps.

Trade candles are not mark/index data. This limitation affects stop modeling and execution fidelity.

## Simulator and experiment design

`src/backtest.py` runs the same event-driven bar engine for four preregistered candidates: 4h trend + 1h Donchian breakout; 4h trend + 1h momentum/price structure; breakout + retest; and EMA pullback. Signals use closed bars and enter at the next 1h open. Initial equity is USD 900 per isolated asset/strategy experiment; risk budget is 0.25%, notional cap is 0.75× equity, one position at a time. Fees are 5 bps per side. Execution friction is 3 bps per side baseline and 7.5 bps per side in stress. Hourly funding is applied where Kraken data exists. Missing funding coverage is explicitly recorded on every result row.

The experiment writes 224 scenario metrics (assets × strategies × seven chronological windows × baseline/stress) and 4,935 trade rows. Windows are train 0–55%, validation 55–65%, four sequential walk-forward windows 65–85%, and a final holdout 85–100%. Parameters are fixed across windows; the holdout must not be used for parameter tuning. Since the holdout was evaluated across 16 asset/strategy candidates, picking the single best row is subject to multiple-comparison bias.

## Final holdout snapshot

Dates: **2026-05-22 to 2026-11-02**, starting equity USD 900 separately for every row. All these rows have complete funding coverage.

| Asset / candidate | Baseline net return | PF | Trades | Max drawdown | Stress net return | Stress PF |
|---|---:|---:|---:|---:|---:|---:|
| ETH breakout + retest | +16.31% | 1.89 | 33 | -7.09% | +14.12% | 1.74 |
| ETH momentum + price structure | +8.80% | 1.69 | 20 | -6.08% | +8.06% | 1.63 |
| ETH trend + Donchian | +5.21% | 1.53 | 14 | -6.55% | +4.29% | 1.42 |
| SOL momentum + price structure | +4.65% | 1.43 | 16 | -6.65% | +3.70% | 1.33 |
| BTC momentum + price structure | +0.60% | 1.04 | 25 | -7.02% | +0.96% | 1.08 |
| XRP momentum + price structure | +2.27% | 1.15 | 104 | -3.26% | -0.15% | 0.99 |

These are individual-asset candidate screens, not a combined portfolio. The best-looking row was selected among many candidates and misses the configured 6% peak drawdown budget. It does not establish durable positive expectancy. Full metrics and trade ledgers are in `results/metrics.csv`, `results/metrics.json` and `results/trades.csv`.

## Decision

**NO-GO for paper/live promotion.** Do not call any candidate profitable yet. The final holdout is only about 5.5 months, the favorable candidate is ETH-specific and was one of 16 simultaneous candidates, and recorded drawdown exceeds the 6% limit. Earlier walk-forward windows cannot be interpreted as fully net because funding history is unavailable for part of them. The test also uses trade OHLC proxies for stop execution and lacks tick-level spread, order-book depth, partial-fill, liquidation and historical contract-spec modeling. The 10% weekly/monthly aspiration is not achieved or substantiated here.

## Next work

1. Find a defensible way to source complete historical Kraken funding or set a conservative missing-history funding stress; do not silently substitute zero.
2. Implement the prior-chat design as a portfolio test: weekly 14/30/60-day cross-sectional momentum as a market selector, 4h structure, then a 1h pullback + break-of-structure entry. Enforce one total position across all assets, rather than separate independent asset simulations.
3. Add mark-price candles or a justified stop-trigger proxy, tick-size/lot-size and contract-spec history, spread observations, and gap/partial-fill stresses.
4. Keep the final holdout frozen; use a new future period for any candidate selected after the current comparison.


## Portfolio candidate screen (2026-11-02)

A second, portfolio-level screen was run after the isolated-asset results. It allows at most **one open position across BTC, ETH, SOL and XRP** and ranks eligible signals by the strongest sign-aligned 30-day return. The fixed candidate entries are the four existing signal families (`trend_donchian`, `momentum_structure`, `breakout_retest`, `ema_pullback`), with the existing closed-bar 4h trend filter. Signals execute at the next 1h open. Position risk is 0.25% of current equity, notional is capped at 0.75× equity, and the stop starts at 2× ATR with a 3× ATR trail after +1R. The test starts only when Kraken funding history begins (2025-10-30); all observed held hours have funding data except a few identified gaps. This does not repair the missing funding history before that date.

The four entry families and cost stresses were screened with fixed parameters. Cost baseline is 5 bps fee plus 3 bps spread/slippage per side; stress keeps the fee and raises spread/slippage to 7.5 bps per side. Stress trade counts can differ because higher costs change equity and therefore later risk gates/position sizes. Funding is charged at observed hourly rates; 14 held hours are unobserved for the leading baseline run and are counted as missing, not assumed evidence of complete funding coverage.

### Leader by full funding-era net return under stress

| Entry | 2025-10-30 to 2026-11-02 baseline | Stress | Walk-forward 1 baseline | Walk-forward 2 baseline | Final screened window baseline |
|---|---:|---:|---:|---:|---:|
| Breakout + retest | +4.76%, PF 1.23, DD -4.11%, 153 trades | +1.38%, PF 1.07, DD -4.95%, 156 trades | +2.00%, PF 1.44, 34 trades | -2.06%, PF 0.72, 49 trades | +4.86%, PF 1.56, 70 trades |
| 4h trend + Donchian | +1.73%, PF 1.06, DD -6.01%, 201 trades | -2.92%, PF 0.86, DD -6.04%, 153 trades | +3.20% | -2.75% | +1.37% |
| Momentum + price structure | -4.21%, PF 0.85, DD -6.13%, 217 trades | -4.44%, PF 0.75, DD -6.17%, 130 trades | -1.70% | -0.91% | -3.18% |
| EMA pullback | -1.65%, PF 0.90, DD -6.06%, 116 trades | -2.60%, PF 0.84, DD -6.01%, 118 trades | -0.14% | -0.68% | +4.36% |

The leading breakout/retest run had 153 trades in one year (median hold 13 hours); 152 exited at the stop. ETH contributed +$86.15 net, while BTC contributed -$33.34 and XRP -$20.60. This is too much asset concentration and turnover to treat the result as a robust diversified edge. The “final screened window” is 2026-05-22 to 2026-11-02. It was already inspected in the earlier isolated-asset screen, so despite being later in time it is **not an untouched independent holdout**. The portfolio candidate's walk-forward returns change sign between consecutive folds.

**Decision: select breakout + retest as the lead research candidate only; NO-GO for a claim of profitability and NO-GO for paper/live promotion.** Its roughly +1.4% stress result for the full funding-era sample is positive but thin, one chronological fold is negative, and the apparent gains are concentrated in ETH. No candidate establishes a repeatable net edge or the aspirational 10% weekly/monthly return. Continue only with forward paper tracking and a new, predeclared holdout after the rules are frozen; do not optimize to the screened final window.

### Reproduction and artifact map

Run from the repository root:

```bash
python -m src.portfolio_momentum
python -m unittest discover -s tests -v
python -m src.audit_data
```

`src/portfolio_momentum.py` stores the full rule set and writes `results/portfolio_momentum_metrics.json` (including code/data SHA-256 fingerprints), `results/portfolio_momentum_trades.csv`, and `results/portfolio_momentum_equity.csv`. The prior one-asset grid remains in `src/backtest.py` and the original `results/metrics.*`/`trades.csv`. Tests passed (4/4); the data audit passed all 16 files, with the known 5 funding-hour gaps per asset and no candle gaps.

### Research references

- Hudson & Urquhart (2021), *Technical trading and cryptocurrencies*: out-of-sample predictability varied by coin, with no Bitcoin predictability in their tested OOS period. [Springer](https://doi.org/10.1007/s10479-019-03357-1).
- *Dynamic time series momentum of cryptocurrencies* (2021): examines time-series momentum at multiple data frequencies; this motivates testing a slower momentum filter but does not validate this implementation. [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S1062940821000590).
- Bailey et al., *The Probability of Backtest Overfitting*: repeated candidate selection raises the risk of selecting a spurious winner. [UC eScholarship](https://escholarship.org/uc/item/4w1110bb).
