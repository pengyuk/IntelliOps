# IntelliOps 知识沉淀缺口分析

> 基于两份真实故障复盘报告（MCIS交易波动 + BOCS-DNF数据下刷延迟）与当前平台知识库对照梳理  
> 日期：2026-06-07

---

## 一、缺口总览

```
                    目前已覆盖      缺口（需沉淀）
                    ─────────      ────────────
根因规则 (Rules)        4 条         17 条
预警信号 (Signals)      3 条         12 条
SOP 模板 (SOPs)         1 条          8 条
脚本资产 (Scripts)      3 条         10 条
知识图谱节点 (KG)       ~10 个        ~35 个
关键教训 (Learnings)    3 条         11 条
角色/流程元数据          0 条          6 项
```

---

## 二、根因规则缺口（Root Cause Rules）

> 当前 `KnowledgeDistiller` 仅按关键词做粗分类（performance/availability/capacity/configuration/dependency），  
> 缺少银行核心系统特有故障模式。

### 2.1 数据同步与消息中间件类

| # | 规则ID | 故障模式 | 触发条件 | 来源 |
|---|--------|---------|---------|------|
| 1 | `rule-mq-pageset-exhaust` | **MQ Pageset 空间耗尽**：大量数据变更通过 QREP 下刷时，MQ Pageset 使用率持续上升至 75%+ 且不下降，最终导致同步阻塞 | ① MQ Pageset Usage >= 50% 持续 10min ② QREP NamedQueue Depth >= 2,000,000 ③ 历史数据清理批量正在运行 | BOCS-DNF |
| 2 | `rule-qrep-sync-overwhelm` | **QREP 同步速率被压垮**：单日下刷数据量超过 QREP 日常吞吐能力（>1亿/小时），导致 MQ 积压无法在窗口内追平 | ① 单日清理量 > 10亿 ② 清理集中在试点行（物理存储连续→读IO降低→清理加速）③ MQ 传输速率正常但积压持续增长 | BOCS-DNF |
| 3 | `rule-batch-cleanup-capacity` | **变更后首日批量清理容量评估缺失**：批次投产后暂停的历史数据清理恢复首日，清理量叠加导致端到端链路（DB→QREP→MQ→DNF）超载 | ① 批次投产 D+2 日 ② 暂停清理的表 > 20 张 ③ 暂停周期 > 20 天 ④ 未做端到端容量评估 | BOCS-DNF |
| 4 | `rule-data-locality-cleanup-accel` | **试点行数据物理集中导致清理加速**：试点行数据底层物理存储集中 → 删除时获取 page 数减少 → 读 IO 减少 → 清理速度远超预期 → MQ 积压 | ① 清理数据集中在少数分区/行 ② 实际清理速率 > 预估速率 2x ③ 未在测试环境复现此场景 | BOCS-DNF |
| 5 | `rule-mq-tiered-alert-escalation` | **MQ 告警逐级升级但未触发根因定位**：三级(Depth)→二级(Pageset 50%)→一级(Pageset 75%)，告警链完整但缺少"停止清理"的直接建议 | ① 三级告警后 14min 无恢复 ② 告警仅描述现象未关联变更 ③ 未自动关联正在运行的批量作业 | BOCS-DNF |

### 2.2 外部依赖与第三方类

| # | 规则ID | 故障模式 | 触发条件 | 来源 |
|---|--------|---------|---------|------|
| 6 | `rule-thirdparty-service-anomaly` | **第三方机构服务异常**：分行特色业务依赖的外部厂商系统故障，导致交易成功率骤降，但总行侧无法直接修复 | ① 交易成功率 < 70% 连续 3 个采样点 ② 仅特定分行/商户的交易受影响 ③ 总行侧系统（MCIS/CSP）自身健康 | MCIS |
| 7 | `rule-single-tenant-isolation` | **单租户故障隔离**：多第三方单位的业务中仅一家异常，说明租户间隔离有效但缺少差异化告警 | ① 同一接口多家商户仅一家成功率下降 ② 总交易量无明显变化 ③ 自动恢复（第三方自愈） | MCIS |
| 8 | `rule-branch-autonomous-system` | **分行自主开发系统故障**：分行自主开发系统的监控、告警、定位能力弱于总行标准，故障响应依赖人工通知 | ① 分行 CSP 上的特色业务 ② 总行仅能看到 MCIS→CSP 链路 ③ CSP→分行特色→第三方链路不可见 | MCIS |

### 2.3 主机与交易类

| # | 规则ID | 故障模式 | 触发条件 | 来源 |
|---|--------|---------|---------|------|
| 9 | `rule-maxtask-during-cutover` | **DNF 回切期间主机 MaxTask**：数据追平后切换 DNF 时，主机 CICS 出现 MSTK 导致交易拒绝，波及借记卡/支付/跨行支付多系统 | ① 切换前主机 CPU 使用率 > 70% ② MIPS 临时扩容后仍接近上限 ③ 月末/季末交易日峰值 | BOCS-DNF |
| 10 | `rule-cascade-from-host-to-channel` | **主机性能抖动→渠道交易失败链**：主机 MaxTask → C-DBC 超时 → 快捷支付/银联交易失败（交易路径：C-DBC→IPS-D-SAM→BOCS-D/BOCS-DNF） | ① C-DBC 交易成功率 < 99% ② IPPS 成功率同步下降 ③ RCPS-IBPS 成功率同步下降 | BOCS-DNF |

### 2.4 变更管理类

| # | 规则ID | 故障模式 | 触发条件 | 来源 |
|---|--------|---------|---------|------|
| 11 | `rule-change-end-to-end-gap` | **变更端到端评估缺失**：方案讨论仅覆盖表范围和存储空间，未评估 QREP→MQ→DNF 全链路影响 | ① 变更涉及数据清理/迁移 ② 方案评审未包含系统平台部 ③ 恢复策略仅有"分多天清理"未细化每日上限 | BOCS-DNF |
| 12 | `rule-change-implementation-drift` | **方案落地偏离设计**：前期讨论确认"无清理时间要求、分多天执行"，但落地时将全部待删数据合并到单日清单 | ① 方案文档与实际执行脚本不一致 ② 缺少每日清理量上限的技术约束（如 LIMIT 子句） ③ 投产验证未检查清理清单规模 | BOCS-DNF |

### 2.5 监控有效性类

| # | 规则ID | 故障模式 | 触发条件 | 来源 |
|---|--------|---------|---------|------|
| 13 | `rule-monitor-sampling-gap` | **交易监控采样窗口过大**：MCIS 交易成功率监控需多个采样点才能触发告警，导致发现延迟（7:42 发生 → 7:47 发现，5 分钟滞后） | ① 成功率连续 3 个点 < 0.7 ② 采样间隔 > 1min ③ 缺少单点突降即时告警 | MCIS |
| 14 | `rule-dnf-delay-monitor-blind-window` | **DNF 数据下刷延时监控存在盲区**：0:00-7:00 主机批量时段关闭延时告警以避免误报，导致此窗口内异常无法及时发现 | ① 凌晨批量窗口 ② 延时告警被主动屏蔽 ③ 缺少 6:30 预切换前的检查告警 | BOCS-DNF |
| 15 | `rule-no-root-cause-alert` | **有现象告警无根因告警**：两起故障的监控均能发现异常但无法指向根因（报告中均填写"有无根因定位告警：无"） | ① 告警仅报告指标异常 ② 未关联变更窗口 ③ 未关联上下游依赖状态 | 两份报告共性 |
| 16 | `rule-external-report-delay` | **外部报送滞后于实际影响**：网联在 9:59 报送 9:57-9:58 的影响，滞后 2 分钟，且此时故障已实际发生 | ① 外部机构报送时间 > 故障发生时间 ② 缺少外部机构实时通知接口 | BOCS-DNF |
| 17 | `rule-auto-recovery-no-root-cause` | **自动恢复后放弃根因追踪**：故障自动恢复后容易松懈，MCIS 案例中"具体原因湖南行正在排查中"无闭环确认 | ① 故障自动恢复 ② 影响时间短 < 30min ③ 根因在外部系统 | MCIS |

---

## 三、预警信号缺口（Warning Signals）

> 当前 `KnowledgeDistiller` 仅提取 timeline 中已有的 alert 事件，  
> 缺少各系统的**具体指标阈值和告警规则**。

### 3.1 MQ / QREP 类

| # | 信号ID | 指标 | 阈值 | 严重级别 | 来源 |
|---|--------|------|------|---------|------|
| 1 | `sig-mq-queue-depth` | QREP NamedQueue CURRENT DEPTH | >= 2,000,000 | critical | BOCS-DNF |
| 2 | `sig-mq-pageset-usage-warn` | MQ PageSet Usage % | >= 50% | warning | BOCS-DNF |
| 3 | `sig-mq-pageset-usage-crit` | MQ PageSet Usage % | >= 75% | critical | BOCS-DNF |
| 4 | `sig-mq-pageset-usage-emerg` | MQ PageSet Usage % | >= 90% | emergency | BOCS-DNF |
| 5 | `sig-qrep-end-to-end-delay` | QREP 端到端同步延时 | > 10 秒 | critical | BOCS-DNF |
| 6 | `sig-qrep-delay-pre-switch` | DNF 回切前（6:30）QREP 延时检查 | > 10 秒 | critical | BOCS-DNF |

### 3.2 交易成功率类

| # | 信号ID | 指标 | 阈值 | 严重级别 | 来源 |
|---|--------|------|------|---------|------|
| 7 | `sig-txn-success-rate-drop` | 单接口交易成功率 | < 70% 连续 3 个采样点 | high | MCIS |
| 8 | `sig-txn-success-rate-single` | 单接口交易成功率单点突降 | < 50%（单点即刻告警） | critical | MCIS |
| 9 | `sig-cdbc-success-rate` | C-DBC 交易技术成功率 | < 99.5% | critical | BOCS-DNF |
| 10 | `sig-ipps-success-rate` | IPPS 交易技术成功率 | < 99.5% | critical | BOCS-DNF |

### 3.3 主机资源类

| # | 信号ID | 指标 | 阈值 | 严重级别 | 来源 |
|---|--------|------|------|---------|------|
| 11 | `sig-host-maxtask` | 主机 CICS MaxTask | 任何 MSTK 事件 | critical | BOCS-DNF |
| 12 | `sig-host-cpu-pre-peak` | 主机 CPU 使用率（预高峰） | > 85%（预判 10:00 峰值前） | warning | BOCS-DNF |

---

## 四、SOP 模板缺口

> 当前仅有一条通用 SOP，缺少银行核心系统特有的应急处置流程。

| # | SOP ID | 标题 | 步骤概要 | 涉及角色 | 风险级别 | 来源 |
|---|--------|------|---------|---------|---------|------|
| 1 | `sop-external-fault` | **外部/第三方故障应急处置** | ① 确认受影响范围（是否仅特定商户/分行）② 通知对应分行/业务方并行排查 ③ 如属第三方原因，总行侧保持监控无需处置 ④ 自动恢复后确认恢复并记录 | 应用维护、当值经理、分行科技部 | low | MCIS |
| 2 | `sop-mq-pageset-emergency` | **MQ Pageset 堆积应急处置** | ① 登录主机排查 MQ 组件状态（队列深度/Pageset 使用率/死信队列）② 排查联机交易响应时间是否异常 ③ 排查在运行的批量/清理作业 ④ 定位根因后执行停批/降低并发 ⑤ 持续监控 Pageset 下降趋势 ⑥ 必要时下起 QREP 实例加速 | 系统平台、应用维护、开发 | high | BOCS-DNF |
| 3 | `sop-dnf-delayed-cutover` | **DNF 延迟回切应急处置** | ① 评估数据同步预计完成时间 ② 若无法在 7:00 前完成，改为手动回切 ③ 关停准生产释放 MIPS ④ 评估主机高峰期 MIPS 是否需要临时扩容 ⑤ 按同步进度确定先回切的目标机房（黑山扈/其他）⑥ 逐机房执行隔离→切换→开启心跳→接收流量 | 系统平台、应用维护、当值经理 | critical | BOCS-DNF |
| 4 | `sop-stop-historical-cleanup` | **紧急停止历史数据清理** | ① 项目组提供停止清理 SQL ② 评估停止后对清理进度的影响 ③ 在低风险窗口执行停止 ④ 确认 MQ Pageset 开始下降 ⑤ 记录已清理和待清理数据量 | 应用维护、开发一部 | high | BOCS-DNF |
| 5 | `sop-mips-temp-expansion` | **主机 MIPS 临时扩容** | ① 关停准生产释放 MIPS ② 评估当前 CPU 使用率与峰值预测 ③ 计算所需额外 MIPS 量 ④ 执行临时扩容（如 +9420 MIPS）⑤ 扩容后持续监控 CPU | 系统平台 | high | BOCS-DNF |
| 6 | `sop-branch-escalation` | **分行问题升级通报** | ① 确认故障范围限于特定分行 ② 当值经理发送【警示】通告 ③ 服务台通知对应分行科技部/安全经理/主管 ④ 故障恢复后发送【恢复】通告 ⑤ 分行反馈根因后关闭 | 当值经理、服务台、分行 | medium | MCIS |
| 7 | `sop-postmortem-template` | **故障复盘报告标准模板** | ① 生产故障概述 ② 影响分析（系统/业务/关联/账务）③ 应急处置过程（发现/定位/处置/恢复/关键时间点）④ 故障根源分析（直接原因/机制分析/过程执行分析/管理与体系分析）⑤ 存在问题 ⑥ 后续整改方案 ⑦ 故障定级 ⑧ "1-5-15-30-24"达标分析 | 当值经理、事件经理、当值总经理 | — | 两份报告共性 |
| 8 | `sop-data-cleanup-capacity-checklist` | **批量数据清理变更检查清单** | ① 预估每日清理量（总量+分表量）② 评估 QREP 下刷量及速率 ③ 评估 MQ Pageset 容量是否可承载 ④ 制定每日清理上限与超限停止策略 ⑤ 评估试点行数据物理集中对清理速率的影响 ⑥ 端到端链路（DB→Capture→MQ→Apply→DNF）压力评估 ⑦ 制定首日应急预案 | 开发、系统平台、应用维护 | — | BOCS-DNF |

---

## 五、脚本资产缺口

> 当前仅有 3 条通用模拟脚本（日志采集/指标检查/服务重启），  
> 缺少银行核心系统（主机/MQ/QREP/DNF）的专用脚本。

| # | 脚本ID | 名称 | 语言 | 用途 | 风险 | 来源 |
|---|--------|------|------|------|------|------|
| 1 | `scr-stop-historical-cleanup` | 停止历史数据清理 | SQL | 紧急停止正在运行的历史数据清理批量作业 | high | BOCS-DNF |
| 2 | `scr-check-mq-pageset` | 查询 MQ Pageset 使用率 | JCL/Shell | 实时查询 QPS1 PageSet 使用率百分比 | low | BOCS-DNF |
| 3 | `scr-check-qrep-queue-depth` | 查询 QREP 队列深度 | MQSC | 查询 QR.XMITQ1 当前深度及传输速率 | low | BOCS-DNF |
| 4 | `scr-stop-qrep-instance` | 停止/启动 QREP 实例 | MVS Console | 下起指定 QREP 实例以加速 MQ 消费 | high | BOCS-DNF |
| 5 | `scr-mips-temp-expand` | 主机 MIPS 临时扩容 | HMC/zOS | 临时增加 LPAR MIPS 配额 | high | BOCS-DNF |
| 6 | `scr-dnf-cutover-heartbeat` | DNF 心跳开关批量操作 | Shell | 按指定顺序（440/412/490/...）打开 DNF 心跳 | high | BOCS-DNF |
| 7 | `scr-check-dnf-sync-delay` | DNF 数据同步延时检查 | SQL/Python | 查询 QREP Apply 端延迟，对比主机 DB2 与 DNF Oracle 数据差异 | low | BOCS-DNF |
| 8 | `scr-check-mcis-csp-success-rate` | MCIS→CSP 接口成功率检查 | Python | 按商户/分行维度统计 MCIS 到 CSP 的调用成功率 | low | MCIS |
| 9 | `scr-dump-txn-by-merchant` | 按商户维度导出交易明细 | SQL | 异常时段内按商户维度统计交易量/成功率，用于隔离第三方故障 | low | MCIS |
| 10 | `scr-check-cdbc-cascade` | C-DBC 关联系统成功率检查 | Python | 同时检查 C-DBC/IPPS/RCPS-IBPS 成功率，判断是否为 MaxTask 级联影响 | low | BOCS-DNF |

---

## 六、知识图谱节点缺口

> 当前 `sample_kg.json` 仅有 ~10 个通用模拟节点（svc-payment, svc-order 等），  
> 缺少两份报告中涉及的真实系统。

### 6.1 需新增的系统节点

```
应用系统:
├── BOCS-D       (E03401, A5/1类, 核心银行系统-国内, z/OS + DB2)
├── BOCS-DNF     (分布式非金融核心银行系统, Oracle, 黑山扈信创)
├── MCIS         (E10944, 多渠道接入系统)
├── MCIS-CHL     (多渠道接入系统-渠道接入)
├── BIBP-CSPA    (分行中间业务平台, 2类, KylinServer + TDSQL)
├── C-DBC        (C00211, A5/1类, 借记卡系统)
├── IPPS         (E03600, A4/1类, 网上支付处理系统)
├── RCPS-IBPS    (E04001, A5/1类, 人民币跨行支付系统-网上支付)
├── IPS-D-SAM    (借记卡路由/服务适配)
├── BOCNET       (网上银行)

中间件/基础设施:
├── QREP-MQ      (主机→DNF 数据同步通道, IBM MQ for z/OS)
├── QREP-CAPTURE (主机端 DB2 日志抓取)
├── QREP-APPLY   (DNF 端 Oracle 写入)
├── CICS         (主机交易中间件)
├── DB2-zOS      (主机数据库)
├── Oracle-DNF   (DNF 数据库)

外部系统:
├── 网联          (外部清算机构)
├── 长沙建南电子   (第三方餐卡行业卡系统)
├── 湖南分行CSP    (分行云平台上的特色系统)
└── 湖南分行特色系统 (分行自主开发)

主机/LPAR:
├── 黑山扈主机     (MIPS 111,210, 内存 1280GB, 磁盘 831TB)
└── 黑山扈信创主机  (x86 DNF 部署)
```

### 6.2 需新增的关系边

```
依赖关系 (depends_on):
  C-DBC → IPS-D-SAM → BOCS-D (主机查询路径)
  C-DBC → IPS-D-SAM → BOCS-DNF (DNF 查询路径)
  MCIS → BIBP-CSPA (分行特色调用)
  BIBP-CSPA → 湖南分行特色系统
  湖南分行特色系统 → 长沙建南电子 (第三方)
  BOCNET → MCIS

数据同步 (data_sync):
  BOCS-D → QREP-CAPTURE → QREP-MQ → QREP-APPLY → BOCS-DNF

切换关系 (cutover):
  BOCS-D ←→ BOCS-DNF (7:00 切 DNF, 2:00 切回主机)

交易路径 (txn_flow):
  手机银行 → BOCNET → MCIS → CSP → 分行特色 → 第三方
  快捷支付 → C-DBC → IPS-D-SAM → BOCS-D/BOCS-DNF
  银联交易 → C-DBC → IPS-D-SAM → BOCS-D/BOCS-DNF
```

---

## 七、关键教训缺口（Key Learnings）

| # | 教训 | 来源 |
|---|------|------|
| 1 | **端到端链路评估是变更评审的必选项**：2603 批次暂停历史数据清理的方案仅讨论了存储空间，未评估 QREP→MQ→DNF 全链路影响，导致 MQ 堆积。此后所有数据清理相关变更必须做端到端容量评估 | BOCS-DNF |
| 2 | **方案设计与落地执行必须可验证一致**：前期讨论"分多天逐步清理"但落地单日清理 25 亿，缺少技术约束（如每日清理量上限的 LIMIT）来保证方案忠实执行 | BOCS-DNF |
| 3 | **试点行数据的物理集中特性会改变清理速率模型**：试点行数据物理存储连续 → page 获取减少 → 清理加速，这个特性在常规清理中不存在，需单独建模 | BOCS-DNF |
| 4 | **凌晨监控盲区需要"预切换检查点"弥补**：DNF 延时监控在 0:00-7:00 关闭，应增加 6:30 的预切换检查告警 | BOCS-DNF |
| 5 | **外部报送不能替代自身监控**：网联 9:59 报送时故障已发生 2 分钟，不能等外部通知才开始响应 | BOCS-DNF |
| 6 | **自动恢复不等于问题解决**：MCIS 案例中故障自动恢复后未深入追查根因，第三方厂商的加密解密模块软件故障可能重复发生 | MCIS |
| 7 | **分行自主开发系统的监控标准应对齐总行**：MCIS→CSP 链路可见但 CSP→分行特色→第三方不可见，需推动分行侧监控接入统一平台 | MCIS |
| 8 | **应急方案应包含精确的操作步骤而非原则性描述**："如何暂停历史数据清理在应急方案中未有详细步骤"，导致夜间紧急沟通确认耗时 47 分钟 | BOCS-DNF |
| 9 | **单租户隔离的有效性是重要的防护网**：MCIS 案例中仅 1/5 第三方商户受影响，说明租户隔离有效——但这本身应作为知识资产记录而非隐含假设 | MCIS |
| 10 | **MIPS 临时扩容的触发阈值应固化为规则**：当 CPU > 85% 且预计高峰前无法完成操作时自动建议扩容，而非人工判断 | BOCS-DNF |
| 11 | **1-5-15-30-24 达标分析应自动化**：两份报告均手工计算各阶段耗时与偏差，平台应根据 Timeline 自动生成 SLA 达成报告 | 两份报告共性 |

---

## 八、角色与流程元数据缺口

> 当前仅定义了 4 个通用角色（operator/developer/approver/admin），  
> 缺少银行科技运营中心的真实角色体系。

| # | 元数据类型 | 缺失内容 | 来源 |
|---|-----------|---------|------|
| 1 | **角色定义** | 当值总经理、当值主管、当值经理、值班经理、应用维护一部/二部、系统平台一部/三部、开发一部、服务台、安全经理、分行科技部 | 两份报告 |
| 2 | **升级路径** | 一线值班→维护A角→值班经理→当值经理→当值主管→当值总经理 的逐级升级规则 | 两份报告 |
| 3 | **通告模板** | 【预警】【警示】【恢复】三种通告的标准格式与发送范围 | 两份报告 |
| 4 | **故障定级规则** | 五级/四级故障的判定标准（服务中断时长、影响交易量、涉及系统等级） | BOCS-DNF |
| 5 | **SLA 框架** | "1-5-15-30-24" 目标（1 分钟发现、5 分钟响应、15 分钟定位、30 分钟恢复、24 小时根因分析） | 两份报告 |
| 6 | **应急组织机制** | 7X24 小时应急机制启动条件、ECC 大厅到场规则、行信通报流程 | BOCS-DNF |

---

## 九、模拟场景缺口

> 当前 `/incidents/simulate` 有 4 个预设场景（db_timeout/cpu_spike/mq_backlog/network_flap），  
> `mq_backlog` 场景（BOCS-D→BOCS-DNF QREP 堆积 12 万条）已部分覆盖 BOCS-DNF 案例，但缺少以下场景：

| # | 场景名 | 描述 | 对应真实案例 |
|---|--------|------|-------------|
| 1 | `qrep_pageset_exhaust` | MQ Pageset 使用率从 52%→76%→90% 逐级恶化，QREP 深度超 200 万，与历史数据清理批量叠加 | BOCS-DNF |
| 2 | `thirdparty_branch_failure` | 分行第三方商户服务异常，MCIS→CSP 单接口成功率 45.5%，自动恢复 | MCIS |
| 3 | `maxtask_during_cutover` | DNF 回切期间主机 MaxTask，C-DBC/IPPS/RCPS 三级联失败 | BOCS-DNF |
| 4 | `batch_cleanup_new_batch` | 变更后首日历史数据清理量异常增大（25 亿），QREP 同步延迟超 40 分钟 | BOCS-DNF |

---

## 十、建议的沉淀优先级

```
Priority 0 (立即) — 可直接写入 sample_kg.json 和现有模板:
├── 17 条根因规则 → 写入 skill/incident-diagnosis/references/root-cause-patterns.md
├── 12 条预警信号 → 写入 skill/log-analysis/references/error-patterns.md
├── 35 个 KG 节点 → 写入 kg/sample_kg.json
└── 4 个模拟场景 → 写入 app.py simulate_incident() 的 templates

Priority 1 (本周) — 需新建文件:
├── 8 条 SOP 模板 → 新建 skill/war-room-coordination/references/sop-library.md
├── 10 条脚本资产 → 写入 skill/script-operations/assets/
└── 11 条关键教训 → 写入 docs/learnings.md

Priority 2 (下周) — 需代码改动:
├── 角色体系升级 → 修改 app.py USERS/PERMISSIONS
├── 故障定级引擎 → 新增 POST /incident/{id}/classify
├── SLA 自动分析 → 新增 GET /incident/{id}/sla-analysis
└── 通告模板 → 新增 notification 模块
```
