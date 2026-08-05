# Scanner Performance Follow-up

Production evidence from August 5 showed approximately 30 symbols processed in
7.5 minutes, or about 15 seconds per symbol. At that observed rate, a sequential
68-symbol scan would take approximately 17 minutes. That delay can be material
for intraday opportunity detection.

The scanner currently processes symbols sequentially and completes
`generate_signal(symbol)` before advancing to the next symbol. Existing telemetry
does not attribute the observed time among provider requests, option-chain work,
indicator calculation, persistence, retries, or network latency.

The next performance task should instrument `generate_signal()` and the scan loop
with monotonic stage timings for:

- market-data/provider requests;
- option-chain retrieval;
- indicator and scoring calculations;
- authoritative persistence;
- retry, backoff, and intentional sleep time;
- per-symbol total and full-run total.

Measurements should include counts, percentiles, cache hits, and rate-limit events
without logging credentials or payload secrets. Only after production measurements
should bounded concurrency, batching, or caching be evaluated against provider
limits and deterministic scanner behavior.

This observability branch intentionally does not change concurrency, caching,
providers, scanner universe, qualification, scoring, lifecycle, or execution.
