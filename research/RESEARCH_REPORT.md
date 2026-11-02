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

## Concurrent-position and 3–4% budget sensitivity (2026-11-02)

The next experiment keeps the breakout/retest signals and 30-day cross-asset rank fixed, but allows one, two, or four simultaneous positions. It caps each coin at one open position, ranks same-hour candidates by momentum, sizes each from distance to stop, and retains the daily -1%, weekly -3% and peak-drawdown -6% **new-entry halts**. Costs and funding are charged as in the prior screen. The peak/daily/weekly thresholds stop new entries; they do not forcibly liquidate positions already open, so realized adverse drawdown can exceed the threshold.

| Position / sizing case | Full funding-era baseline | Stress costs | Peak drawdown baseline / stress |
|---|---:|---:|---:|
| 1 position, 0.25% equity risk to stop | +4.76%, PF 1.23, 153 trades | +1.38%, PF 1.07, 156 trades | -4.11% / -4.95% |
| 2 positions, 0.25% risk each (0.5% max planned combined) | -3.41%, PF 0.58, 53 trades | -3.65%, PF 0.54, 53 trades | -6.07% / -6.09% |
| 4 positions, 0.25% risk each (1% combined) | -2.73%, PF 0.68, 59 trades | -3.08%, PF 0.63, 59 trades | -6.15% / -6.26% |
| 4 positions, 0.75% risk each (3% combined) | +4.12%, PF 1.41, 31 trades | +2.89%, PF 1.29, 31 trades | -6.94% / -6.56% |
| 4 positions, 1.00% risk each (4% combined) | +3.14%, PF 1.22, 28 trades | +6.15%, PF 1.68, 23 trades | -9.68% / -7.06% |
| 4 positions, 3% of equity allocated as margin each, max 2× leverage; stop risk still capped at 0.25% each | -4.64%, PF 0.66, 175 trades | -4.93%, PF 0.64, 167 trades | -6.04% / -6.24% |
| 4 positions, 4% of equity allocated as margin each, max 2× leverage; stop risk still capped at 0.25% each | -4.20%, PF 0.47, 70 trades | -4.48%, PF 0.44, 70 trades | -6.03% / -6.19% |

**Interpretation:** allowing more positions did not reliably capture profitable opportunities. At the conservative 0.25% stop-risk budget, two and four slots lost money and reached the drawdown gate; the trade-entry halt then reduced subsequent activity. The 3–4% aggregate stop-risk cases had positive returns in this sample, but breached the configured 6% peak-drawdown threshold in both baseline and stress, and the 4% case reached -9.68% baseline. They fail the capital-protection objective. The 3–4% *margin allocation* cases are a different, much smaller risk exposure (3–4% margin per position, up to 2× notional; stop risk remains capped), and both lost around 4–5% net. Neither interpretation supports increasing the live budget.

As a concentration diagnostic, the 367 aligned daily return observations from the funding-era window show pairwise BTC/ETH/SOL/XRP close-return correlations from **0.825 to 0.908**. This is a historical sample statistic, not a stable future constant, but it explains why four open alt/crypto positions can behave like one larger directional bet. Research also finds crypto correlations and diversification benefits vary across assets and time scales. [CME's four-asset study](https://www.cmegroup.com/articles/2025/diversifying-crypto-portfolios-with-xrp-and-sol.html); [hourly/daily spillover study](https://doi.org/10.1016/j.econmod.2024.106728).

**Risk decision:** keep one open position as the research default. Do not raise stop-risk to 3–4% of equity across simultaneous trades; the tested versions violate the drawdown limit. If “3–4% per trade” means margin allocation, document it as margin/notional, not risk; the tested 3–4% allocation cases still did not improve net results. Revisit concurrency only after improving signal quality and evaluating a new untouched forward period. No candidate is promoted to paper/live.

Reproduce this screen from the repository root with `python -m src.portfolio_concurrency`. It writes `results/portfolio_concurrency_metrics.json`, `results/portfolio_concurrency_trades.csv`, and `results/portfolio_concurrency_equity.csv`; metrics include code/data hashes and each scenario's planned aggregate stop-risk. The four data-store tests continue to pass.

## Follow-up search: slower trend filters and retest ranges (2026-11-02)

The earlier screens found that the 1h breakout/retest was the strongest candidate but generated 153 trades/year, was concentrated in ETH, and lost money in one chronological fold. I kept that 24h range as the benchmark and tested only two predeclared follow-ups: longer 72h/168h 1h breakout/retest ranges, and slower 4h entries filtered by a completed daily 50/200 EMA regime. The 4h entries were Donchian-20 breakout, breakout/retest-20, and EMA-20 pullback. These are exploratory screens on the same approximately one-year complete-funding window; the final interval had already been examined and is not a new independent holdout.

| Candidate, full funding-era window | Baseline net return / PF / trades | Stress net return / PF / trades | Max drawdown baseline / stress |
|---|---:|---:|---:|
| 1h breakout/retest, 24h range (benchmark) | +4.76% / 1.23 / 153 | +1.38% / 1.07 / 156 | -4.11% / -4.95% |
| 1h breakout/retest, 72h range | +1.01% / 1.09 / 88 | -0.09% / 0.99 / 88 | -4.79% / -4.98% |
| 1h breakout/retest, 168h range | +0.73% / 1.09 / 57 | +0.13% / 1.02 / 57 | -4.34% / -4.47% |
| 4h Donchian-20 + daily 50/200 regime | -2.50% / 0.65 / 45 | -2.69% / 0.62 / 45 | -3.23% / -3.34% |
| 4h breakout/retest-20 + daily regime | -1.34% / 0.71 / 29 | -1.66% / 0.65 / 30 | -2.32% / -2.32% |
| 4h EMA-20 pullback + daily regime | -2.37% / 0.74 / 65 | -2.62% / 0.70 / 65 | -3.52% / -3.72% |

The longer retest ranges lowered trade count but did not improve net stress performance. All three slower 4h candidates lost money both before and after cost stress; each walk-forward fold was also negative for the 4h methods. This is a useful negative result: simply slowing the system or adding a daily trend filter did not reveal an edge in this sample. The 24h benchmark remains the least-bad candidate, but its thin stressed return and negative WF fold still do not qualify it as reliably profitable.

This direction is consistent with the research motivation to test momentum/trend at multiple frequencies, while other studies emphasize that transaction costs can change the profitability of technical rules by asset and frequency. The evidence does not warrant importing a published result directly into this Kraken strategy. [Dynamic time-series momentum study](https://www.sciencedirect.com/science/article/pii/S1062940821000590); [technical rules and transaction costs study](https://www.sciencedirect.com/science/article/pii/S1042443122000816).

### Current conclusion and next research gate

**No reliable profitable strategy has been found yet.** Do not expand the indicator/parameter grid simply to search for a positive row: that would increase selection bias without fixing the short, previously screened funding sample. Keep the 24h breakout/retest as a benchmark hypothesis only; no live or paper promotion. The next useful research investment is execution/data quality (mark-price OHLC, historical bid/ask and slippage, complete or conservatively stressed funding) plus a frozen future paper period, rather than more tuning on the same holdout. A strategy must be positive net of stress costs in both walk-forward folds and a new untouched period while staying below the 6% drawdown limit before reconsideration.

Reproduce the new screens from the repository root:

```bash
python -m src.retest_lookback_screen
python -m src.slow_trend_screen
```

Outputs include code/data hashes, chronological fold metrics, complete trade ledgers and equity curves under `results/retest_lookback_*` and `results/slow_trend_*`.

## Follow-up search: side, volume and stop-width hypotheses (2026-11-02)

The current 1h breakout/retest trade ledger shows why a side filter merited a controlled test: in the all-sides baseline, 59 long trades contributed +$37.74 net while 94 short trades contributed +$5.08, after fees/funding. This is a result from the tested sample, not a universal claim about crypto shorts. I tested a predeclared long-only version, a 1.5× prior-24h average volume confirmation, a BTC 4h trend-direction gate, and long-only plus the volume gate. All retain one global position, 0.25% equity stop risk and the same transaction-cost/funding assumptions.

| Variant | Funding-era baseline | Stress | Baseline / stress max drawdown |
|---|---:|---:|---:|
| All sides (benchmark) | +4.76%, PF 1.23, 153 trades | +1.38%, PF 1.07, 156 trades | -4.11% / -4.95% |
| Long-only | +4.15%, PF 1.50, 60 trades | +2.02%, PF 1.23, 63 trades | -2.06% / -2.45% |
| Volume >= 1.5× prior 24h mean | -0.41%, PF 0.97, 112 trades | -2.16%, PF 0.86, 114 trades | -4.62% / -5.29% |
| Require direction to agree with BTC 4h regime | +1.16%, PF 1.07, 130 trades | -1.28%, PF 0.93, 133 trades | -2.85% / -4.36% |
| Long-only + volume confirmation | +0.38%, PF 1.05, 46 trades | -0.84%, PF 0.89, 48 trades | -2.26% / -2.72% |

Long-only is the best new research candidate so far: it lowered turnover and drawdown and raised the stress result from +1.38% to +2.02%, while its baseline return was slightly lower (+4.15% versus +4.76%). But the first and second walk-forward folds were both negative: -0.16% and -0.13% baseline (the first fold had just five trades); stress was -0.20% and -0.82%. The later screened window was positive but is not independent. The long-only full-window result also remained ETH-heavy: ETH contributed +$43.64, while BTC contributed -$13.30; SOL and XRP were close to flat. It therefore remains a hypothesis, not a validated strategy.

I also compared the long-only version at 2×ATR and 3×ATR initial stops while holding the 0.25% per-trade risk budget constant. The wider 3×ATR stop reduced full-window return to +2.31% baseline / +1.05% stress, with a 1.91% drawdown; both walk-forward folds remained negative. It did not improve returns enough to replace 2×ATR.

Volume was a plausible filter because published work studies return/volume links, but its empirical relationship is mixed and implementation costs vary by coin and rule. Published momentum evidence also differs on whether returns come from long or short legs. Our ledger motivated the long-only test; it cannot establish that the same effect will persist. [Trend and volume in Bitcoin](https://link.springer.com/article/10.1007/s40822-021-00166-5); [transaction costs and technical rules](https://www.sciencedirect.com/science/article/pii/S1042443122000816); [economic constraints on crypto anomalies](https://doi.org/10.1016/j.irfa.2024.103218).

### Updated decision

**No reliably profitable strategy has cleared the evidence bar.** Keep long-only 1h breakout/retest with a 2×ATR initial stop and 0.25% risk as the current lead *for research tracking only*. Its net stress return (+2.02% over the funding-era year) is promising relative to prior variants, but its two chronological folds are negative and the later positive period was already screened. Do not promote it to paper/live or increase risk. Freeze this version; obtain a genuinely new forward sample and better mark-price/execution data before testing further rule changes. The aim is to avoid selecting a positive-looking result from repeated searches on the same history.

Reproduce from repository root:

```bash
python -m src.hypothesis_filter_screen
python -m src.long_only_stop_screen
```

The two scripts save parameterized metrics with code/data hashes, trade ledgers and equity curves under `results/filter_hypothesis_*` and `results/long_only_stop_*`. The filter screen also writes a daily-sampled equity export, which is the compact curve archived to GitHub.

## Indicator confirmation test: Bollinger Bands, RSI and OBV (2026-11-02)

On the frozen long-only 1h breakout/retest lead, I tested conventional, fixed confirmations without tuning: BB(20,2) requires the prior completed hourly close to finish above its 20-period SMA + 2 population standard deviations; RSI uses Wilder(14) and must be at least 50 at the retest close; OBV must be higher than five bars earlier. The combined variant requires all three. All cases retain the same one-position, 0.25%-risk, next-hour entry, stops, fee, spread/slippage and observed funding model.

| Variant | Full funding-era baseline | Stress | DD baseline / stress | Trades base / stress |
|---|---:|---:|---:|---:|
| Long-only lead | +4.15%, PF 1.50 | +2.02%, PF 1.23 | -2.06% / -2.45% | 60 / 63 |
| + Bollinger confirmation | +4.68%, PF 1.61 | +2.70%, PF 1.33 | -2.20% / -2.42% | 57 / 60 |
| + RSI(14) >= 50 | +4.15%, PF 1.50 | +2.02%, PF 1.23 | -2.06% / -2.45% | 60 / 63 |
| + OBV rising over 5 bars | +3.71%, PF 1.43 | +1.46%, PF 1.16 | -2.06% / -2.44% | 60 / 63 |
| + Bollinger + RSI + OBV | +4.24%, PF 1.53 | +2.14%, PF 1.25 | -2.20% / -2.42% | 57 / 60 |

Bollinger alone added about 0.53 percentage points baseline and 0.68 points under stress relative to the long-only lead, with virtually unchanged drawdown. But it did not pass the stability check: WF1 remained -0.16% (five trades), WF2 was +0.11% baseline and -0.58% under stress, and the later +4.73% baseline window was already screened. RSI filtered no trades: every selected long signal already had RSI >= 50. OBV reduced the return, and adding RSI/OBV to Bollinger diluted its full-period gain. Therefore **Bollinger is a candidate confirmation to freeze for future paper observation, not evidence of a proven edge**. Do not tune its period or deviation multiplier on these same dates.

This is consistent with the broader caution that technical-rule profitability is sensitive to transaction costs, while volume-price relationships are not a sufficient standalone confirmation. [Technical rules and transaction costs](https://www.sciencedirect.com/science/article/pii/S1042443122000816); [trend/volume relationship study](https://link.springer.com/article/10.1007/s40822-021-00166-5).

Reproduce with `python -m src.indicator_confirmation_screen`. Metrics include fixed rule definitions and code/data hashes; trade logs, hourly equity and daily-sampled equity exports are written to `results/indicator_confirmation_*`.
