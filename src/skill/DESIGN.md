# Skill 组件设计（基于 VS Code Copilot Skill 机制）

## 定位

> IntelliOps 的 Skill 组件不是传统的 Python 应用模块，而是基于 **VS Code Copilot Agent Skills** 机制构建的一组领域专用 `SKILL.md` 文件。每个 Skill 教会 AI 代理（Copilot）如何执行特定的应急排查任务——从诊断到处置到复盘。

**核心理念**：后端 API（Person A+B 已实现）提供**能力**，Skill 文件提供**知识和流程**。AI 代理加载 Skill 后，知道"何时调用哪个 API、如何解读结果、下一步该做什么"。

```
┌─────────────────────────────────────────────────────────────┐
│                    VS Code Copilot（AI 代理）                 │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐  │
│  │incident- │  │ log-     │  │ postmor- │  │knowledge- │  │
│  │diagnosis │  │analysis  │  │tem-gen   │  │retrieval  │  │
│  │.SKILL.md │  │.SKILL.md │  │.SKILL.md │  │.SKILL.md  │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬─────┘  │
│       │             │             │               │        │
│  ┌────┴─────────────┴─────────────┴───────────────┴──────┐ │
│  │              工具调用（API / CLI）                       │ │
│  │   POST /copilot/diagnose   POST /copilot/chat          │ │
│  │   GET  /script/suggest     POST /script/execute        │ │
│  │   GET  /kg/query           POST /incident/{id}/postmortem│ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## VS Code Copilot Skill 机制速览

Skill 是 Copilot 的**可插拔知识包**，放在特定目录下即被自动发现：

```
.github/skills/<skill-name>/
├── SKILL.md           # 必须：元数据 + 指令（name 必须匹配文件夹名）
├── scripts/           # 可执行脚本（Python/Bash）
├── references/        # 参考文档（按需加载）
└── assets/            # 模板、样板文件
```

### SKILL.md 格式

```yaml
---
name: skill-name              # 必须：1-64 字符，小写+连字符
description: '何时使用的描述。最多 1024 字符。包含触发关键词。'
argument-hint: '可选的 / 命令参数提示'
user-invocable: true          # 是否显示为斜杠命令（默认 true）
disable-model-invocation: false  # 是否禁止模型自动加载
---
# Skill 标题

## 何时使用
- 触发条件与使用场景

## 步骤
1. 第一步
2. 第二步

## 参考
- [脚本](./scripts/check.sh)
- [模板](./assets/template.json)
```

### 渐进式加载（节省上下文）

| 阶段 | 加载内容 | Token 消耗 |
|------|---------|-----------|
| 发现 | `name` + `description` | ~100 |
| 加载 | `SKILL.md` 正文（匹配时） | <5000 |
| 资源 | `references/` 文件（被引用时） | 按需 |

### 核心原则
1. **关键词丰富的 description**：AI 通过 description 匹配来决定是否加载 Skill
2. **渐进式加载**：SKILL.md 控制在 500 行以内，细节放 references/
3. **相对路径**：资源引用始终用 `./`
4. **自包含**：Skill 包含完成任务所需的全部流程知识

---

## IntelliOps Skill 体系设计

基于 IDEAS.md 和 MODULE_ARCHITECTURE.md 的架构蓝图，以及 Person A 已完成的 6 个后端模块，设计以下 Skill 技能树：

```
src/skill/
├── DESIGN.md                 # 本设计文档
├── sample_skill.json         # 旧版意图示例（保留）
│
├── incident-diagnosis/       # 故障诊断 Skill（核心）
│   ├── SKILL.md
│   └── references/
│       ├── diagnosis-api.md      # API 参考
│       └── root-cause-patterns.md # 常见根因模式
│
├── log-analysis/             # 日志分析 Skill
│   ├── SKILL.md
│   └── references/
│       ├── error-patterns.md     # 错误模式词典
│       └── correlation-rules.md  # 跨源关联规则
│
├── script-operations/        # 脚本管理 Skill
│   ├── SKILL.md
│   ├── assets/
│   │   └── script-template.py   # 脚本生成模板
│   └── references/
│       └── risk-matrix.md        # 风险分级矩阵
│
├── postmortem-generator/     # 复盘生成 Skill
│   └── SKILL.md
│
├── knowledge-retrieval/      # 知识检索 Skill
│   ├── SKILL.md
│   └── references/
│       └── kg-query-patterns.md # KG 查询模式
│
├── war-room-coordination/    # War Room 协同 Skill
│   ├── SKILL.md
│   └── references/
│       └── role-matrix.md       # 角色+通知规则
│
├── data-analysis/            # 运维指标分析（适配 Skill）
│   └── SKILL.md
│
├── git-incident-docs/        # 文档版本管理（适配 Skill）
│   └── SKILL.md
│
└── code-review-scripts/      # 脚本审查（适配 Skill）
    └── SKILL.md
```

---

## 各 Skill 详细设计

### Skill 1: `incident-diagnosis`（故障诊断）

**定位**：核心 Skill，编排故障诊断全流程。AI 加载此 Skill 后能独立完成"接收故障 → 调用诊断 API → 解读结果 → 推荐下一步"。

```yaml
---
name: incident-diagnosis
description: >
  故障应急诊断与根因推理。
  触发词：故障、事故、incident、诊断、根因、排查、告警、延迟、错误率、CPU高、内存泄漏。
  使用场景：运维人员报告故障时、告警触发时、需要分析根因时。
argument-hint: '<incident_id 或故障描述>'
---
```

**流程**：
1. 解析用户输入，提取 incident_id 或故障现象
2. 调用 `POST /copilot/diagnose` 启动诊断会话
3. 展示根因候选（含置信度+证据链）和日志分析摘要
4. 引导用户补充信息，调用 `POST /copilot/chat` 多轮交互
5. 根据置信度变化推荐"收集更多证据"或"进入处置"

**依赖的 API**：
- `POST /copilot/diagnose`
- `POST /copilot/chat`
- `GET /incident/{id}/related-cases`
- `GET /kg/query`

**所属层级**：认知层 + 智能体层，直接消费 Person A 的 reasoner/log_analyzer/copilot

---

### Skill 2: `log-analysis`（日志分析）

**定位**：教会 AI 如何解读原始日志、识别异常模式、执行跨源关联。

```yaml
---
name: log-analysis
description: >
  智能日志分析与异常检测。
  触发词：日志、log、错误日志、ERROR、堆栈、异常、报错、trace、slow query。
  使用场景：收到日志片段需要分析时、需要关联多源日志时。
---
```

**流程**：
1. 接收用户粘贴的日志或指定日志来源
2. 调用 `LogAnalyzer.analyze()` 或直接使用内置规则
3. 输出：摘要、关键事件（按严重度排序）、异常模式、跨源关联
4. 将分析结果注入当前诊断上下文

**依赖的 API**：Person A 的 `log_analyzer.py`（规则引擎 + LLM 分析）

**参考文档**：`references/error-patterns.md` — 运维领域 10+ 常见错误模式正则库

---

### Skill 3: `script-operations`（脚本管理）

**定位**：管理诊断/处置脚本的生命周期——生成、验证、执行、永久化。

```yaml
---
name: script-operations
description: >
  应急脚本生成、预执行校验与安全执行。
  触发词：脚本、执行、运行、命令、修复、重启、检查、预执行、dry-run。
  使用场景：需要生成诊断脚本时、需要验证脚本安全性时、需要执行处置操作时。
---
```

**流程**：
1. 调用 `GET /script/suggest` 获取推荐脚本
2. 对高风险脚本，先调用 `POST /script/verify` 做 dry-run
3. 用户确认后调用 `POST /script/execute`
4. 执行结果自动回传 Copilot 继续分析
5. 成功的脚本可标记为 `permanent` 入库

**参考文档**：`references/risk-matrix.md` — 操作风险分级（low/medium/high）及审批要求

---

### Skill 4: `postmortem-generator`（复盘生成）

**定位**：故障恢复后自动生成结构化复盘报告，并蒸馏知识资产。

```yaml
---
name: postmortem-generator
description: >
  自动生成故障复盘报告并提取知识资产。
  触发词：复盘、总结、报告、回顾、postmortem、故障分析报告、改进措施。
  使用场景：故障恢复后、需要生成复盘文档时、需要提炼经验教训时。
---
```

**流程**：
1. 调用 `POST /incident/{id}/postmortem` 生成报告（含时间线、根因、决策）
2. 自动调用 `KnowledgeDistiller.distill()` 提取可复用知识
3. 展示：根因规则、预警信号、SOP 模板、脚本推荐、关键教训
4. 调用 `POST /postmortem/{id}/approve` 审批发布

**依赖的 API**：
- `POST /incident/{id}/postmortem`
- `GET /postmortem/{id}/knowledge`（Person A 的 knowledge_distiller）

---

### Skill 5: `knowledge-retrieval`（知识检索）

**定位**：教会 AI 高效检索知识图谱、历史案例、SOP 模板。

```yaml
---
name: knowledge-retrieval
description: >
  知识图谱查询、相似案例检索、SOP 推荐。
  触发词：查一下、搜索、案例、SOP、知识库、有没有类似的、历史故障、依赖关系。
  使用场景：需要查找历史相似案例时、需要查询服务依赖时、需要获取 SOP 时。
---
```

**流程**：
1. 解析查询意图（实体查询 / 关系查询 / 相似案例）
2. 调用 `GET /kg/query`、`GET /kg/subgraph`、`GET /incident/{id}/related-cases`
3. 格式化输出：节点+边、案例卡片、SOP 步骤
4. 将检索结果注入诊断上下文

**依赖的 API**：Person B 的 KG 查询接口 + 向量检索接口

---

### Skill 6: `war-room-coordination`（War Room 协同）

**定位**：多人协同场景下的信息同步、角色通知、状态广播。

```yaml
---
name: war-room-coordination
description: >
  多人应急协同与信息同步。
  触发词：通知、@、同步、协同、拉人、指派、DBA、开发、值班、谁在处理。
  使用场景：需要通知相关人员时、需要同步排查进度时、需要指派任务时。
---
```

**流程**：
1. 根据故障类型自动推荐需通知的角色
2. 调用 `POST /incident/{id}/discussion` 发送协同消息
3. 通过 WebSocket 广播状态更新
4. 自动生成进度摘要

**依赖的 API**：
- `GET /auth/users`（查询角色）
- `POST /incident/{id}/discussion`（发送消息）
- Person B 的 WebSocket（实时推送）

---

## 可下载 vs 需自研

### 可直接下载使用的通用 Skills

以下 Skill 可从 VS Code Marketplace / GitHub 社区获取，直接使用或略微调整：

| Skill | 来源 | 用途 | 适配成本 |
|-------|------|------|---------|
| **REST API Client** | Marketplace 通用 | 调用 IntelliOps API 的基础 HTTP 能力 | 零成本，Copilot 内置 |
| **Code Review / Analysis** | GitHub 社区 | 审查生成的脚本代码质量和安全性 | 低，调整 review 规则 |
| **Git Workflow** | Marketplace 通用 | 复盘报告、SOP 模板的版本管理 | 零成本 |
| **Markdown/文档生成** | Copilot 内置 | 生成格式化的复盘报告和知识卡片 | 零成本 |
| **Terminal Command** | Copilot 内置 | 执行 Shell 命令（替代部分 Harness 功能） | 零成本 |
| **Web Search** | Copilot 内置 | 搜索公开的故障案例和技术文档 | 零成本 |
| **Data Analysis** | Marketplace | 分析监控指标 CSV/JSON 数据 | 低，配置数据 schema |

### 需要自行开发的领域 Skills

以下 Skill 包含 IntelliOps 特有的领域知识和 API 调用流程，必须自研：

| Skill | 复杂度 | 预估 | 关键自研内容 |
|-------|--------|------|-------------|
| `incident-diagnosis` | 🔴 高 | 5d | 诊断流程编排、API 调用序列、根因解读逻辑、多轮对话策略 |
| `log-analysis` | 🟡 中 | 3d | 错误模式库、跨源关联规则、日志→诊断的桥接逻辑 |
| `script-operations` | 🟡 中 | 3d | 脚本分类模板、风险矩阵、执行回传逻辑 |
| `postmortem-generator` | 🟡 中 | 2d | 报告模板、知识蒸馏触发、审批流程 |
| `knowledge-retrieval` | 🟡 中 | 2d | KG 查询模式、案例相似度解读、SOP 匹配规则 |
| `war-room-coordination` | 🟢 低 | 2d | 角色通知规则、状态广播格式 |

**自研总计：≈ 17 人天**（与 Person A/B 的接口实现同步推进）

---

## 与已实现模块的关系

Skill 不替代已有代码，而是作为**AI 代理的"使用手册"**：

| Person A/B 模块 | Skill 如何使用 |
|-----------------|---------------|
| `llm_client.py` | Skill 不直接调用；AI 代理通过 API 端点间接触发 |
| `reasoner.py` | `incident-diagnosis` Skill 指导 AI 调用 `/copilot/diagnose` |
| `log_analyzer.py` | `log-analysis` Skill 指导 AI 解读 `log_analysis` 字段 |
| `copilot.py` | `incident-diagnosis` Skill 指导多轮对话策略 |
| `credibility.py` | Skill 的提示词中包含"优先信任高 credibility_level 的结果" |
| `knowledge_distiller.py` | `postmortem-generator` Skill 触发 `/postmortem/{id}/knowledge` |

**关键**: `copilot.py` 已实现 Skill 的"对话+推理"核心闭环。Skill 文件的增量价值是将这套能力**包装为 AI 可直接消费的领域知识**，让 Copilot 知道"何时调用、如何解读、下一步做什么"。

---

## 设计原则

1. **关键词驱动发现**：每个 Skill 的 `description` 包含中英文触发词，确保 AI 在合适时机加载
2. **API 驱动执行**：Skill 不包含业务逻辑（逻辑在 Person A/B 的 Python 代码中），只指导 API 调用序列
3. **渐进式加载**：SKILL.md 保持精简（<300 行），细节放 `references/`
4. **领域知识内置**：自研 Skill 的 `references/` 包含运维领域特有的错误模式、风险矩阵、查询范式
5. **与 UI 解耦**：Skill 面向 AI 代理，不直接生成 UI；前端 Person B 负责展示
6. **安全优先**：`script-operations` Skill 强制高风险操作走 dry-run + 审批流程

---

## 迭代建议

1. **MVP 阶段**（当前）
   - 先交付 `incident-diagnosis` + `log-analysis` 两个核心 Skill
   - 验证 "AI 加载 Skill → 调用诊断 API → 解读结果" 闭环
   - 使用 Copilot Chat 的 `/` 命令手动触发

2. **第二阶段**
   - 加入 `script-operations` + `knowledge-retrieval`
   - 实现 "诊断 → 脚本生成 → 执行 → 回传" 完整链路

3. **第三阶段**
   - 加入 `postmortem-generator` + `war-room-coordination`
   - 实现端到端 "告警→诊断→协同→处置→复盘→知识入库" 自动化
