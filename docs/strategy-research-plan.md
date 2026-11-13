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

## 2026-11-03 stage

Collect separate unadjusted history with isolated adjustment-basis cache identities. Retain all15 volatile listings and all8 fixed variants; run4 fee/lot scenarios at3 local-currency capitals (1440 simulations). Current lots and US1/HK5 minimum fees are explicit assumptions, not historical verified lots or actual broker tariffs. Disclose cash-only/zero-fill paths and the raw-price/corporate-action limitations. Fix trend state transitions on actual fills; prove existing default aggregates unchanged. Add China Telecom H1 issuer cash-coverage evidence without approving dividend safety. Separate forward observations by market/day count. Next: point-in-time lot/corporate-action verification, execution rejection diagnosis, and cash-flow/lease/debt reconciliation.

## 2026-11-04 stage

Keep engine, signals and universe unchanged. Reuse the saved raw experiment to replay360 diagnostic paths with identical metrics and60 actual-execution boundary checks; distinguish initial50% affordability from subsequent10% order intent. Gather partial primary lot anchors for Tencent/Xiaomi/Alibaba without claiming complete continuity or proposal implementation. Read and visually verify original China Telecom cash-flow pages48/49, preserving management/cash-CAPEX, lease, working-capital and dividend-timing gaps. Next: complete corporate-action/lot-change chains and define an executable sizing protocol before further forward validation.

## 2026-11-05 stage

Predeclare a supplementary one-million-local-unit capital comparison on the existing raw-price historical window, then run480 paths across15 listings,8 fixed rules and4 execution models. Capital choice follows prior diagnostics, so it is not untouched validation or an optimal-capital claim. Verify fractional scale invariance and all initial fills; keep return, drawdown and exposure comparisons by market. Frozen forward rules remain unchanged. Add CCB H1/Q3 issuer releases and one interim proposal, preserving A/H issuer identity, announcement timing, approval gaps and the completeFY2025 ordinary DPS base. Capital/provision/NIM evidence remains partial, not a dividend-safety approval. Next: reconcile bank regulatory/stress headroom and ordinary-profit payout denominator, then examine per-stock/rising-versus-falling grid failures without selecting thresholds on inspected results.

## 2026-11-06 stage

Predeclare four consecutive three-month resets within the inspected temporal test, retaining15 volatile listings,8 rules and5 training-only monthly exposure controls:780 simulations across60 dependent stock-blocks. Each block restarts capital and state, so do not concatenate block returns or describe them as an untouched holdout. Ex-post rising/falling/sideways labels explain performance only; the sideways endpoint band does not mean low within-block volatility. Verify120 passive-return identities and75 training-only targets. Keep adjusted-price/fractional results distinct from the previous raw-price/lot experiment. Download and visually verify CCB Q3 KM1 printedp2 and both pages of the interim proposal; add regulatory buffers and issuer payout denominator without declaring distributable headroom or shareholder approval. Next: separate reset effects from continuous position/anchor paths, and verify ordinary-profit/other-equity claims plus the actual approval/payment chain.

## 2026-11-07 stage

Replay195 full-year paths on frozen Nov6 inputs:120 fixed rules exactly reproduce saved results and75 controls retain training-only targets. Preserve positions, anchors, trend state and pending orders across4 windows. Compare780 open-aligned continuous slices with resets; separately bridge overnight PnL and reconcile4 close-aligned returns, trades and fees to all195 annual paths. Keep regime labels descriptive and avoid attributing the joint reset effect solely to anchors or sizing. Verify CCB IFRS note14 printedp98 visually:169564 minus796 equals168768 million ordinary profit. Label proposed-distribution/ordinary-profit sensitivity separately from reported31.0%; no new dividend event or safety approval. Maintain short chat conclusions and full private structured reports. Next: inspect carry-state failures at the boundaries and original approval/payment evidence, without optimizing thresholds on inspected history.

## 2026-11-08 stage

Predeclare six fixed5% grid diagnostic states over all45 noninitial quarter boundaries, yielding270 paths on frozen Nov6 data. Reproduce45 continuous and45 reset paths plus45 entry-fee identities. Compare inherited exposure, actual-fill anchors and pending signals conditionally; report interactions. Cost-free boundary half-weight assignments are diagnostic interventions, not executable rebalancing or a new profitable rule. Keep all8 fixed-rule daily results, original cohort and forward protocol. Verify China Telecom FY2025 interim and final-update HKEX forms visually; add installment-specific HKD conversions, shareholder approval and dated calendars without promoting scheduled payment to paid or an FX update to the original declaration. Preserve the known2026 interim cut and incomplete coverage. Weekend data reuse adds no new observations. Next: test a predeclared executable sizing control including actual boundary fees, and continue dividend cash/safety reconciliation.

## 2026-11-09 stage

Predeclare4 calendar/grid policies and3 cost scenarios on frozen Nov6 data, retaining15 original volatile listings:180 grid-policy plus135 native full/half/monthly benchmark paths. At fixed Feb/May/Aug boundaries suppress old signals for nonoriginal policies, and execute funded50% rebalance orders with actual simulated fees/dust; separately compare keeping the grid anchor versus reanchoring only on fills. Validate45 exact native-grid replays and reconstruct78225 daily balances without capital injection. Report fee sensitivity, issuer/market statistics and worsening stocks; fractional proportional-fee feasibility is not complete real execution or fresh OOS. Verify Telecom annual note37 printedp217: two prior cash events become issuer-reported-paid, while FY2025 final board-date knowledge does not establish original publication timing or final payment. Preserve partial safety status. Audit fresh CN/HK sessions separately from adjusted-history revisions, including ICBC-H repricing and turnover-only changes. Next: minimum-fee/lot constraints and training-based exposure controls for the predeclared sizing policies; continue final-payment and sector cash-safety evidence.

## 2026-11-10 stage

Predeclare a matched raw-price execution comparison:15 frozen volatile listings,4 Nov9 grid/calendar policies plus3 baselines,3 previously studied local-currency capitals and4 fractional/lot/minimum-fee models =1260 paths. Reuse Nov3 raw history/current lot snapshot; validate180 native-grid replays,312900 daily balances,30726 fill/fee/lot identities and210 proportional fractional scaling pairs. Keep HKD/USD results separate and distinguish failed initial entries/late calendar entries from timing skill. Raw corporate-action and lot-history gaps remain, so do not equate this with actual executable profits or attribute adjusted/raw differences purely to costs. Verify cached Telecom interim note19 printedp63 plus the initial March24 cash-dividend form: FY2025 final becomes issuer-reported-paid, original announcement date becomes known, but initial future approval/pending FX dates stay separate and investor receipts/complete PIT history remain unverified. Next: exposure-comparable controls and implementability eligibility on the fixed policies; reconcile dividend cash period and remaining older event/coverage gaps.

## 2026-11-11 stage

Predeclare360 adjusted-price paths on frozen Nov6 data:4 existing grid/calendar policies across15 listings and2 fee scenarios, each with a training path, an inspected-test path and a monthly control whose target is its own training mean exposure. Extend the fixed Nov-start quarterly calendar to training without tuning; validate120 normalized Nov9 test replays,30 native training grids,120 frozen targets and179352 daily balances/30018 fills. Training-only targets do not match test risk: report actual exposure/drawdown gaps and both HK/US results; do not call a small mean return advantage alpha. Keep nominal affordability separate, using raw last-training closes and the later Nov3 lot snapshot without filtering the cohort; all15 pass the1m local-capital diagnostic, which is not historical eligibility or next-open assurance. Verify Telecom's original Aug20 interim cash form, record date and stated FX, retaining scheduled/paid and board/shareholder distinctions. Safety/backtest status stays incomplete. Next: preserve all policies/cohort while decomposing predeclared monthly return and exposure paths; verify remaining older dividend versions and sector cash coverage.

## 2026-11-12 stage

Predeclare accounting attribution of the240 continuous test/control paths saved Nov11, keeping4 policies,15 listings and2 fee scenarios. Partition all12 calendar months without resets or new signals. Reconstruct59600 daily overnight/intraday/fee PnL identities and6304 fills; reconcile2880 monthly slices additively to initial-capital returns and multiplicatively to time returns, plus120 annual pair spreads. Report both markets, issuer balance, exposure gaps and all policies. Default quarter-keep's0.4281pp annual relative return contains2.8215pp from July, with other months totaling-2.3934pp; this is an inspected-path accounting concentration, not a July-only strategy. Verify Telecom's original FY2024 interim cash form, ordinary nature and older date/FX fields; failed annual-report retrieval leaves payment confirmation unverified. No dividend backtest/safety approval or forward-rule change. Next: predeclare a comparison with a calendar-only quarterly50% policy to separate grid contribution from funded quarterly sizing, retaining failures and training-only controls; continue primary dividend/cash-coverage gaps.

## 2026-11-13 stage

Predeclare a funded calendar-only quarterly50% policy with no grid and its own training-exposure monthly control. Execute180 paths (quarter training/test/monthly controls plus native full/half/monthly test baselines), retaining15 listings and2 fees; separately replay240 unchanged grid/control paths. Validate600 opening target/dust opportunities,90 normalized native replays,30 new targets,120 unchanged targets,126788 daily balances and7464 fills. Default quarter-only returns-11.9676% versus grid-quarter-keep-10.8630%, but the latter has7.3552pp more exposure/3.7693pp deeper drawdown; HK worsens and the overall50bp edge reverses. Pure quarter-only also trails monthly50 by0.7130pp. Keep the existing forward protocol and do not call different-benchmark spreads a historical return improvement. Reuse cached Telecom annual note39 printed218 to add historical year-end contracted capital commitments, preserving timing/overlap gaps, unknown old payment and incomplete safety. Next: matched raw whole-lot/minimum-fee verification for the new calendar-only baseline, retaining all stocks and fixed rules; bridge capital commitments to actual dated cash outflows.
