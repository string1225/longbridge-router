# Two independent stock research tracks

User direction, 2026-11-01: study more examples, decide how to develop each approach, and deliver a daily staged report. Dividend stocks use price and dividends; volatile stocks use price only. Do not mix their aggregate conclusions.

## Deliverables

- A maintained candidate universe, a cached read-only Longbridge data collector, price-only simulations with fixed variants and time splits, and primary-source dividend evidence.
- Daily research continues in this chat at 20:00 Asia/Shanghai, beginning 2026-11-02. Each report describes new evidence, current conclusions, failures, uncertainty and the next experiment.
- Raw market data, research API credentials and machine-readable daily results stay outside Git under the private research directory. Public research source and issuer facts are versioned.

## Methods

Dividend track: normalize ordinary distributions by fiscal period and announcement time, distinguish payment calendars from sustainable annual amounts, remove specials, use proper currency/share units and sector-specific coverage. Do not backfill current yields or claim strategy returns without a point-in-time event ledger.

Price track: select volatile candidates using training-period prices, not dividend fields. Compare fixed bounded grid3/5/8%, daily5% reversal and price breakout/trailing-stop rules with full/half hold and monthly half-weight rebalance. Use next-open fills, costs, position bounds and no borrowing. Separate descriptive regimes and time-split historical checks from genuine future paper observations. Report exposure alongside return and drawdown.

Initial window: 2021-11-01 through each market's latest completed session. Training ends2025-10-31; later history is an already-inspected temporal test, not an untouched holdout. No automated trading or purchases of data products.

Protocol v1 also reserves a separate indicative forward-paper period from 2026-11-02. Rules and cohort changes require an explicit version and must not overwrite prior evidence. Daily reports verify matching dataset/universe fingerprints and disclose rejected OHLC records.

## Implementation and verification

- [x] Create a narrowly scoped research credential and private client config.
- [x] Test and implement cached collection, expiry/redirect protection and completed-session date handling.
- [x] Implement and test price-only simulation independently.
- [x] Gather issuer dividend/cut/calendar evidence independently.
- [x] Collect expanded examples, run fixed comparisons and save an initial structured report.
- [x] Create and verify the daily thread automation.
- [x] Run verification, inspect intended changes, commit and push.

Initial verification: 71 tests and Ruff passed; independent review findings were fixed and rechecked. All36 histories through2026-10-30 were collected without HTTP errors; repeat collection used36 cache hits and6 market-summary requests. Fixed base/zero-cost/50bp experiments and the initial2026-11-01 report are stored under the private research root. Four invalid OHLC rows are disclosed and excluded. Dividend event completeness and sector coverage remain ongoing research, not completed backtest claims.

## 2026-11-02 stage

Keep the universe and original forward rules fixed. Add training-only monthly exposure controls and explicitly retrospective mean-exposure-matched controls; report listing and issuer-balanced statistics separately. Suppress annualization below30 observations. Recheck China Telecom's original dividend-history page and add seven dated H-share historical cash events, without inventing announcement timestamps or FX. Preserve the private daily report, data revision audit and experiment provenance. Next: board-lot/minimum-fee sensitivity and announcement-time/sector coverage gaps.
