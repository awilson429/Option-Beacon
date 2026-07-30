# OptionBeacon 2.0 Data Capability Map

## Audit basis

This map reflects repository implementation, not provider marketing promises.
Provider account entitlements, exchange agreements, and quotas must be checked
before relying on a field. Costs and limits are described qualitatively because
they vary by account and can change.

Status:

- **Current:** Implemented and used.
- **Existing-provider extension:** Provider is configured, but a new adapter or
  endpoint is needed.
- **New provider:** No dependable current path.
- **Optional future:** Not required for MVP.

## Capability matrix

| Capability | Status and provider | History / latency | Cost, limits, reliability, licensing | MVP |
|---|---|---|---|---|
| SPY/QQQ OHLCV | Current: Yahoo Finance via `yfinance` | Intraday research fetch supports roughly 60 days at 5m; live delay/freshness is provider-dependent | No explicit repository quota; unofficial/provider-managed behavior and redistribution limits; gaps possible | Required |
| Intraday symbol OHLCV/volume | Current: Yahoo scanner and replay paths | 1m-60m/daily intervals supported by library; current research normalizes 5m timestamps | Rate limits undocumented; reliability adequate for research with quality checks, not guaranteed exchange-grade | Required |
| Premarket/extended hours | Not requested by current scanner/research path; Yahoo may expose it with configuration | Depth and latency not validated | Coverage and adjustment/session semantics require audit | Useful, not required for first MVP; required for gap playbooks |
| Current equity quotes | Current: Finnhub quote abstraction; scanner prices may also be reused | Snapshot only in implemented Finnhub path | Account-tier quota; failures handled; quote entitlement/latency must be disclosed | Required for open tracking; OHLCV fallback is not equivalent |
| Daily mover universe | Current: Finnhub quotes over a configured candidate universe | Current snapshot, not historical candles | Request volume scales by symbols; cached/bounded use required | Optional discovery enhancement |
| General market news | Current: Finnhub general news in After Hours | Current feed; historical coverage not audited | Account tier and publisher rights; duplication and relevance limitations | Optional context |
| Earnings/company schedule | Existing-provider extension: Finnhub may expose endpoints; no verified integrated event-risk adapter | Not audited | Quota, completeness, revisions, and licensing must be validated | Useful; UNKNOWN is acceptable in MVP |
| Economic calendar | New provider or vetted public source | None implemented | Timezone, revisions, reliability, and redistribution are material concerns | Display as unavailable in MVP |
| Sentiment | No structured current implementation | None | Requires model/provider validation and licensing; high semantic error risk | Exclude from MVP decisions |
| Options chains | Current: Tradier expirations and chains | Live/current snapshots; no repository historical chain store | Entitlement/rate limits; exchange data terms; request only when needed | Required only for contract context, not thesis |
| Option quotes | Current: Tradier by option symbol | Current snapshots for open paper positions | Failure-safe; market-closed and stale semantics required | Required for paper option tracking |
| Implied volatility | Available in Tradier chain fields when returned; current capture supports IV | No validated historical IV baseline | Missing fields and entitlement possible; no percentile without history | Optional descriptive MVP field |
| Option open interest/volume | Available in Tradier chain/capture where returned | Current chain snapshot | Intraday update timing and missing values must be disclosed | Liquidity context for paper contracts |
| Unusual options activity | No implementation | None | Likely premium/new provider; ambiguous definitions and licensing | Exclude |
| Put/call measures | No implementation | None | Requires aggregate market/options feed and clear methodology | Exclude |
| VIX | Candidate universe includes volatility proxy `VIXY`; true VIX feed not established | Proxy OHLCV may be available through Yahoo | Proxy is not the index; label honestly | Realized-volatility proxy in MVP; true VIX optional |
| Sector ETFs | Current scan universe and sector mapping in market intelligence | Same Yahoo/scanner limitations | Proxy alignment, not constituent breadth | Required MVP proxy |
| Market breadth | No true breadth feed | None | New provider/exchange data likely required | Exclude; do not infer from a few ETFs |
| Market internals | No tick/TRIN/advance-decline implementation | None | New real-time provider, entitlements, and exchange licensing | Exclude |
| Scheduled corporate events | Partial existing-provider potential; no unified point-in-time adapter | None validated | Revisions and coverage need verification | UNKNOWN state in MVP |
| Historical outcomes | Current JSONL history loaders, trade analytics, journals, and paper stores | Local history since capture began | Runtime files are not durable shared cloud storage by default; malformed rows are skipped safely | Required for paper evaluation |
| Replay datasets | Current normalized Yahoo research pipeline, manifests, hashes, baseline, EXP-001/2/3 | Current manifests define available periods | Retrieval itself is not deterministic; committed hash/normalized artifacts provide reproducibility | Required |

## Existing implementation notes

### Yahoo Finance

Used by the production scanner and research generators for OHLCV. The research
normalizer records source, symbol, interval, timezone, duplicates, missing
bars, and hashes. Retrieval can change between runs, so frozen normalized
datasets and manifests are required for reproducible claims.

### Finnhub

Implemented for credentials, current quotes, daily/attention movers, and
general news. The repository has no Finnhub historical-candle adapter, no
formal economic-event engine, and no validated sentiment pipeline.

### Tradier

Implemented for option expirations, chains, contract capture, and current
option-symbol quotes. It also supports immutable contract snapshots and a
separate paper-position lifecycle. Options evidence must remain downstream of
the underlying thesis.

## MVP data policy

The MVP should rely primarily on:

- SPY, QQQ, symbol, and sector ETF OHLCV;
- timestamps, volume, VWAP derived from validated bars;
- existing current quote abstractions;
- existing Tradier option liquidity fields when available;
- existing paper outcomes and replay infrastructure.

Event risk is explicitly `UNKNOWN` without a calendar. Sentiment, true breadth,
market internals, unusual options activity, and put/call measures do not
contribute to MVP evidence.

## Data-quality contract

Every source result must record:

- provider and endpoint/adapter version;
- symbol and asset type;
- event, received, and evaluation timestamps;
- timezone and session;
- delayed/live/unknown latency designation;
- completeness, staleness, duplicates, and validation errors;
- entitlement/missing-field status;
- dataset or payload hash where persisted.

No provider failure may become a neutral zero or a supporting signal.

## Priority gaps

1. Validated extended-hours bars for Morning Brief and gap playbooks.
2. Durable point-in-time normalized intraday datasets beyond short Yahoo
   windows.
3. Reliable economic and corporate-event calendar.
4. Explicit quote latency/entitlement metadata.
5. Historical IV if IV regime becomes decision-relevant.
6. Durable hosted persistence for long-running paper research.

Breadth, internals, sentiment, and unusual-options data should be evaluated
only after the core OHLCV-based MVP proves useful.
