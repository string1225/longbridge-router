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

`dividend_review.json` 是原始公告证据与缺口清单。已有27份来源、25条部分事件记录，不是完整历史信号库。缺少公告时点、支付历史与覆盖数据时，不宣称股息策略已完成盈利回测。美国最新季度/月度股息年化只是指示值，与已实现年度总额分别展示。不能用除息导致的价格下降凭空制造收益；未来收益模型要计入实际持有资格、应收股息、支付现金、税费与汇率。

波动路线的选股与信号仅使用价格：

- 训练段：2021-11-01起至2025-10-31；显式波动候选需至少126个训练期日收益，年化波动率至少30%。
- 历史时间测试：2025-11-01至2026-10-30，已被查看，不能称为未经查看的样本外证据。
- 前向观察：2026-11-02起单列 `forward_paper`；首个已完成交易日之前不生成虚假结果。固定本版规则和候选池，有变动需另记协议版本，不改写旧结论。
- 固定对照：全仓持有、半仓持有、每月回到50%、3/5/8%网格、单日5%反转、20日价格突破配5%收盘回撤退出。
- 网格以最近实际成交开盘价为锚，收盘上涨阈值卖、下跌阈值买，每次信号时净值的10%；单日5%反转用上一交易日收盘作比较。趋势法突破此前20日最高价时目标80%，自入场成交日起最高收盘价回落5%时目标20%。信号均在下一已观察交易日开盘成交。
- 网格/反转以50%起仓；下单约束20%至80%，自然涨跌可使仓位漂移。无杠杆、无卖空；使用碎股。低于成交时净值1%的零碎调整不执行。最后一天信号不成交，不强制期末平仓。
- 模型默认单边成本：CN/US10bp、HK25bp（含佣金滑点的研究假设，不是券商报价）。另测零成本、全部市场50bp压力情景。现金不计息，未建模最低收费、税费、汇率、整手或流动性限制。
- 每项同时看累计收益、年化、各股最大回撤、交易次数、费用、平均仓位，和同一股票的基准比较。不能把低仓位少亏直接归因为择时能力。按市场和事后上涨/下跌/震荡分组仅用于解释，不能拿事后分组作买卖信号。

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
