Kraken Futures research data and SHA-256 manifests are stored here. Candles cover BTC/ETH/SOL/XRP × 1h/4h/1d from 2023-11-02 through the latest fully completed bar available at download time. Hourly relative funding history is available from Kraken's public endpoint for only a limited recent window (about one year in this capture); manifests state exact first/last rows, missing buckets, and coverage ratio. Missing rates must not be treated as zero or interpreted as evidence of zero funding. The backtester records coverage and flags any experiment with missing funding coverage.

Update efficiently with:

```bash
python -m src.data_store --update --allow-gaps
```

Do not forward-fill missing bars or funding rates. Preserve manifests with the CSVs when copying or publishing the dataset.
