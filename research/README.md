# 两类股票研究与每日报告

研究协议 v1，建立于 2026-11-01。两个股票池独立筛选、模拟和下结论。只读取行情和公开公告，不使用交易接口。

## 当前样本与判断方法

`universe.json` 保存18个股息候选代码、15个波动候选代码和3个基准，共36个代码。工商银行、建设银行的A/H，以及阿里ADR/港股须按发行人合并看风险；代码数不等于独立公司数。手选样本有存续和选择偏差。

股息路线先做分红账本与安全性筛选，再谈估值和收益回测：

1. 逐笔记录普通/特别股息、所属财年、每股或每10股单位、币种、公告版本、除息和支付日期。用当时已公开的信息生成信号，不能把今天的股息率倒填历史。
2. 电信看资本开支后的自由现金流、债务；银行看资本充足率、资产质量和利润覆盖；能源看低油价/煤价情景；REIT看AFFO及融资成本。同一个股息率门槛不能直接覆盖所有行业。
3. 计算普通可持续年度股息 `D_base`，另算削减情景 `D_stress`。价格使用未复权现价，与股息保持同一股数和币种。支付频次改变、特别股息或人民币/港币变化必须先核对。
4. 入场同时满足安全性、基准收益率和压力收益率门槛，分批调整；股价上涨使收益率降至较低退出线时减仓。出现减息或覆盖恶化时单独复核，不因股价下跌使表面收益率变高而机械加仓。买卖门槛之间留间隔，避免来回交易。

仅作算术示例：每股年度普通股息1元，假设研究买入门槛7%、减仓线6%，对应价格14.29和16.67元。若压力股息0.8元且压力收益率需6%，入场价格上限进一步降到13.33元。门槛尚未验证，不是统一交易参数。

`dividend_review.json` 是原始公告证据与缺口清单。截至2026-11-02有27份来源、32条部分事件记录，不是完整历史信号库。新增7条是从中国电信官网补录的FY2021末期至FY2024 H股历史分红，不是当天宣布的新分红；原始公告时点仍未知。缺少公告时点、支付历史与覆盖数据时，不宣称股息策略已完成盈利回测。美国最新季度/月度股息年化只是指示值，与已实现年度总额分别展示。不能用除息导致的价格下降凭空制造收益；未来收益模型要计入实际持有资格、应收股息、支付现金、税费与汇率。

波动路线的选股与信号仅使用价格：

- 训练段：2021-11-01起至2025-10-31；显式波动候选需至少126个训练期日收益，年化波动率至少30%。
- 历史时间测试：2025-11-01至2026-10-30，已被查看，不能称为未经查看的样本外证据。
- 前向观察：2026-11-02起单列 `forward_paper`；首个已完成交易日之前不生成虚假结果。固定本版规则和候选池，有变动需另记协议版本，不改写旧结论。
- 固定对照：全仓持有、半仓持有、每月回到50%、3/5/8%网格、单日5%反转、20日价格突破配5%收盘回撤退出。
- 网格以最近实际成交开盘价为锚，收盘上涨阈值卖、下跌阈值买，每次信号时净值的10%；单日5%反转用上一交易日收盘作比较。趋势法突破此前20日最高价时目标80%，自入场成交日起最高收盘价回落5%时目标20%。信号均在下一已观察交易日开盘成交。
- 网格/反转以50%起仓；下单约束20%至80%，自然涨跌可使仓位漂移。无杠杆、无卖空；使用碎股。低于成交时净值1%的零碎调整不执行。最后一天信号不成交，不强制期末平仓。
- 模型默认单边成本：CN/US10bp、HK25bp（含佣金滑点的研究假设，不是券商报价）。另测零成本、全部市场50bp压力情景。现金不计息，未建模最低收费、税费、汇率、整手或流动性限制。
- 每项同时看累计收益、年化、各股最大回撤、交易次数、费用、平均仓位，和同一股票的基准比较。不能把低仓位少亏直接归因为择时能力。按市场和事后上涨/下跌/震荡分组仅用于解释，不能拿事后分组作买卖信号。
- 少于30根日K时不报告CAGR，避免把前向观察首日收益外推成年化；累计收益和交易记录照常保存。此项只改统计展示，不改变交易规则。

## 仓位对照实验（2026-11-02）

`research.exposure_lab` 使用同一波动池和已查看的2025-11至2026-10历史测试，新增两种逐股月度再平衡对照，沿用原引擎成本、开盘成交和1%净值零碎调整门槛：

- `training_control`：每股目标仓位取该规则在2025-10-31以前的平均仓位，只用训练期确定。测试期实际仓位会漂移，不能称为完全相同风险。
- `posthoc_control`：读取整个历史测试期的平均仓位，事后标定每股月度目标以匹配它。它使用未来信息，只用于解释历史；不可作为交易策略或样本外证据。匹配平均仓位仍未匹配每日仓位路径或市场beta。保存标定残差，不能把平均仓位相同等同于风险相同。

同时计算逐代码均值与发行人均值；后者先在同一发行人的代码内平均，再在发行人之间等权，避免阿里ADR/H股重复加权。均不是跨币种可投资组合。新对照不改变已冻结的前向策略规则或股票池。

沿用下文设置的 `$researchRoot` 和 `$researchDay` 后运行：

```powershell
.\.venv\Scripts\python.exe -m research.exposure_lab --input "$researchRoot/datasets/$researchDay.json" --universe research/universe.json --wave "$researchRoot/experiments/$researchDay-wave.json" --output "$researchRoot/experiments/$researchDay-exposure.json"
```

补充实验与逐行历史修订审计保存在私有日报的 `supplementary_experiments`，当日研究结论与下一项实验在 `daily_progress`。运行基础 `research.report` 后再附加这些内容，并保留补充实验原文件。股息公告读取失败时记录HTTP状态与缺口，不推断日期；各来源复核日期单独记录，不把一份来源复核写成全部来源已更新。

## 整手与最低收费压力实验（2026-11-03）

`research.friction_lab` 保留原波动候选池，另用未复权日K，在同一价格口径下比较4种模型：碎股比例费用、碎股加最低收费、整手比例费用、整手加最低收费。每只股票分别使用1000/10000/100000本币资金，全部8条固定规则都保留；HKD与USD资金不作跨币种汇总。最低收费情景设为每笔港币5元/美元1元，费用取比例费用与最低收费较高值，这不是券商费率表。

整手采用当日接口静态资料，假设回测期间每手股数恒定；未核实历史每手股数变化、拆股、送股、配股或现金分红，不称为真实历史成交重建。信号也使用本实验未复权价格，除息跳空可能触发信号，因此不能把与前复权基准的差异全部归因于费用。所有单据向下取整，不扩大原来每次10%净值的订单以凑一手。无法按规则成交时报告零成交/现金闲置，不能把零收益当作策略优势。

未复权与前复权缓存身份隔离。将 `universe.json` 的波动池复制到私有 `$researchRoot/universe-friction.json`，清空另外两个池，不增加证券代码；使用下文变量后运行：

```powershell
.\.venv\Scripts\python.exe -m research.collect --config "$researchRoot/client.json" --universe "$researchRoot/universe-friction.json" --cache "$researchRoot/cache" --output "$researchRoot/datasets/$researchDay-raw.json" --start 20250901 --adjust-type 0
.\.venv\Scripts\python.exe -m research.friction_lab --raw "$researchRoot/datasets/$researchDay-raw.json" --wave "$researchRoot/experiments/$researchDay-wave.json" --universe research/universe.json --output "$researchRoot/experiments/$researchDay-friction.json"
```

2025-09-01起的数据给2025-11起点提供价格突破预热，本实验结束日固定2026-10-30，属于已查看的历史压力测试。趋势跟踪状态只在实际成交后切换；买入失败不能启动退出跟踪，退出失败保留持仓状态等待重试。已验证该修正不改变当前全部默认碎股历史/前向聚合结果；它修正的是新增整手/拒绝成交路径，原阈值和候选池保持不变。

股息证据现有28份来源、32条部分事件。中国电信2026H1中报新增了一项历史覆盖观察：报告FCF口径为经营净现金流减资本开支，人民币289亿元FCF与归属该期利润的约146.96亿元已宣派中期股息静态相比约1.97倍。这不是上半年实际支付股息覆盖率，仍需核对租赁、营运资金、债务、全年季节性及压力资本开支；不构成分红安全性通过或买入信号。

前向模拟每个市场分别报观察天数：11月3日晚港股有2个已完成交易日，美股有1个。不能把加入美股后的15代码均值与昨日仅5港股的均值直接当作当日收益变化。

## 本机运行

在仓库根目录，Python3.11+：

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[dev,research]'
```

私有根目录为 `C:/Users/junte/.codex/longbridge-strategy-research`，含：

- `client.json`：独立只读应用凭证，包含 `base_url/token/expires_at`。不可输出内容、上传Git或转交其他项目。
- `cache/`：各股前复权历史缓存；`datasets/YYYY-MM-DD.json`：当日行情输入。
- `experiments/`：逐股信号、交易和净值；`reports/`：结构化日报。

下面以首日为例；后续改日期，并让采集器默认取各市场已完成交易日，不要一直传旧的 `--end`：

```powershell
$researchRoot = 'C:/Users/junte/.codex/longbridge-strategy-research'
$researchDay = '2026-11-01'
.\.venv\Scripts\python.exe -m research.collect --config "$researchRoot/client.json" --cache "$researchRoot/cache" --output "$researchRoot/datasets/$researchDay.json" --start 20211101 --end 20261030
.\.venv\Scripts\python.exe -m research.wave_lab --input "$researchRoot/datasets/$researchDay.json" --universe research/universe.json --output "$researchRoot/experiments/$researchDay-wave.json"
.\.venv\Scripts\python.exe -m research.wave_lab --input "$researchRoot/datasets/$researchDay.json" --universe research/universe.json --fee-rate 0 --output "$researchRoot/experiments/$researchDay-zero-cost.json"
.\.venv\Scripts\python.exe -m research.wave_lab --input "$researchRoot/datasets/$researchDay.json" --universe research/universe.json --fee-rate 0.005 --output "$researchRoot/experiments/$researchDay-stress-50bps.json"
.\.venv\Scripts\python.exe -m research.report --dataset "$researchRoot/datasets/$researchDay.json" --wave "$researchRoot/experiments/$researchDay-wave.json" --comparison "zero_cost=$researchRoot/experiments/$researchDay-zero-cost.json" --comparison "stress_50bps=$researchRoot/experiments/$researchDay-stress-50bps.json" --date $researchDay --output "$researchRoot/reports/$researchDay.json"
```

第二天起给 `research.report` 加 `--previous` 指向前一份实际报告，保留各日报文件，不覆盖旧证据。报告追踪历史修订、事件修订和新增来源；下载时间改变不算新增行情。引擎保存输入指纹，报告拒绝混用其他数据或候选池的回测。OHLC无效/重复记录的剔除数必须在报告中披露，不能把缺失行情视为零。

## 采集与权限

使用139中转的固定市场路由：A股直连，港/美股由139代理。无需给研究客户端额外开VPN。不读取管理员密码或长桥OAuth凭证。

仅采已完成日K线，CN/HK按UTC+8交易日，美股按市场本地日。市场假日由返回记录确定；北京时间20:00美股当天通常尚未开盘，日报应注明美国行情来自上一已完成交易日。

前复权缓存不能简单追加：重取60个日历日交集，发现调整基准改变或交集缺失时全量重取；重取失败或丢失旧区间记录时保留旧缓存并报错。按日期分块，防止接口1000条上限截断。历史已缓存时只刷新市场摘要，不重复下载整段历史。

401/403/409或暂停/过期时说明缺口，停止依赖授权的研究；不绕过权限、不自动新建凭证。专用凭证可在管理台撤销，90天后由所有者续期。每周最多增加4个代码，月内默认至多60个研究代码；优先离线实验，不购买数据产品。

## 每日报告与推进顺序

本聊天已有北京时间每天20:00的原生任务，首次2026-11-02，任务名「两类股票策略每日阶段报告」，ID `automation`。修改现有任务，避免创建重复任务；定时运行依赖Codex运行环境可用。

每日先读上份报告，再推进一个可验收问题：补齐某发行人事件链；核对减息；增加费用/整手情景；解释一个失败股票；跨时段复核；或检查前向观察。休市仍可做公告和历史实验，明确当日没有新增行情。

报告交付到本聊天，包含新证据、两池分别的结果、失败案例、变化与可信度、缺口和下一步。保留所有固定规则的结果，不只汇报表现最好的股票或阈值。完整分红事件库与覆盖筛选建好后，才实现股息策略收益回测。

验证：`python -m pytest -q`；`python -m ruff check router research tests deploy skills`。研究代码变更验证后提交并推送；私有行情、凭证和完整实验结果不入Git。生产网关不因离线研究代码变化而重启。
