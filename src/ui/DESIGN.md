# 前端设计（UI）

## 当前实现（2026-06-06，B7 已完成）

> **React + Vite + ECharts SPA**。14 个源文件，覆盖全部后端 API。保留 `index.html` 作为早期原型参考。

### 实现文件

| 文件 | 说明 |
|------|------|
| `package.json` | React 18 + Vite 5 + ECharts 5 + Zustand 4 |
| `vite.config.js` | 开发代理 `/api` → `localhost:8000` |
| `index-react.html` | Vite 入口 HTML |
| `src/main.jsx` | React 入口 |
| `src/App.jsx` | 主布局（5 面板 Grid）+ IncidentSelector + TimelineList |
| `src/store.js` | Zustand 全局状态（API 调用 + WebSocket） |
| `src/hooks/useWebSocket.js` | WebSocket 自动重连 + 事件驱动刷新 |
| `src/components/Header.jsx` | 事故状态、角色切换、操作按钮 |
| `src/components/DiagnosisPanel.jsx` | 根因推理卡片（置信度+进度条+证据链+日志摘要） |
| `src/components/KnowledgePanel.jsx` | 相似案例 + 知识资产 |
| `src/components/ScriptPanel.jsx` | 脚本推荐、预执行、执行+审批 |
| `src/components/DiscussionPanel.jsx` | 多角色讨论 + Copilot 流式回复 |
| `src/components/LogPanel.jsx` | 执行审计日志 |
| `src/components/GraphView.jsx` | ECharts 力导向图（KG 服务依赖可视化） |
| `src/components/PostmortemDialog.jsx` | 复盘报告模态框 |
| `src/index.css` | 全局样式（CSS 变量 + Grid 布局） |
| `src/components/ContextPanel.jsx` | 占位（逻辑已并入 App.jsx） |
| `index.html` | 早期原生 JS 原型（保留参考） |

### 启动方式

```bash
cd src/ui
npm install
npm run dev        # 开发模式（http://localhost:5173，自动代理 :8000）
npm run build      # 生产构建 → dist/
```

### 当前已实现的 5 区域

- **头部**：事故状态、角色切换、Copilot 诊断/复盘按钮
- **左侧**：事故列表、KG 上下文、时间线
- **中央上**：根因推理面板 + 相似案例/知识资产
- **中央下**：脚本建议 + 执行按钮（含 dry-run/审批）
- **右侧**：多角色讨论区（Copilot/运维/开发） + 执行审计日志

### 技术栈

| 维度 | 当前 | 目标（B7） |
|------|------|-----------|
| 框架 | 原生 JS + CSS | ✅ React 18 + Vite + Zustand |
| 状态管理 | 全局 `state` 对象 | ✅ Zustand store（`src/store.js`） |
| 实时更新 | 手动"刷新"按钮 | ✅ WebSocket 自动推送（`useWebSocket` hook） |
| 图可视化 | 无 | ✅ ECharts 力导向图（`GraphView.jsx`） |
| 流式对话 | 无 | ✅ Copilot 回复实时展示（`DiscussionPanel.jsx`） |
| 移动端 | 媒体查询适配 | ✅ 响应式 CSS Grid 布局 |

## 设计核心（保持）

以下设计理念贯穿始终，不受实现方式影响：

- **大模型前置**：自动诊断，而非被动等待
- **人机协同**：Copilot 建议 + 运维决策 + 开发确认
- **可执行优先**：诊断 → 工具/脚本 → 执行
- **透明审计**：置信度、依据、历史全记录
- **知识循环**：故障 → 脚本 → 复盘 → 资产

---

## 核心设计特点

### 1. 大模型 Copilot 前置诊断

故障一接入时自动触发：

- 📊 自动收集30min内日志异常、关键错误、依赖服务状态、最近变更
- 🔍 多候选根因推理，每个都带置信度、证据链、相似案例关联
- 👥 推荐诊断步骤与对应工具/脚本

### 2. 人机协同分析

维护与 Copilot 多轮对话：

`
维护："我已收集支付服务日志，下一步查什么？"
Copilot："很好！建议检查 DB_CONN_ACTIVE 和 QUERY_LATENCY_P99。
我已准备脚本 query_db_metrics.py，需要预执行吗？"
维护："好的，执行一下"
Copilot："[执行结果] 连接数450/500，异常查询27条..."
`

### 3. 多角色讨论与决策记录

维护/开发在讨论区实时沟通，Copilot 监听并整理建议：

`
[运维] 已收集日志，连接数450/500
[开发] 看起来像连接泄漏，建议查pool config
[Copilot总结] 李四建议检查连接池配置，我同意优先排查SpringBoot池设置
[运维] 配置max_connections=50（低于推荐200）
[开发] 可临时加到100测试吗？
[运维] 好的，即将执行...
`

### 4. 可执行工具与自动生成脚本

- **现有工具**（绿色）：直接执行
- **Copilot生成脚本**（黄色）：待审批，可选永久化
- **高危脚本**（红色）：需开发审批

维护可选择脚本的保留方式（一次性/临时/永久）。

### 5. 自动复盘与知识积累

故障恢复后自动生成：

- 完整时间线（触发→接入→诊断→执行→恢复）
- 根因结论与置信度
- 关键决策点与依据
- 执行的工具/脚本清单
- 改进建议

成功脚本和复盘报告自动入库成为知识资产。

---

## 区域详设

### 1. 事故信息头部

- 事故ID/摘要/严重级别
- 状态：新建 → 分析中 → 执行中 → 已恢复 → 复盘中
- 影响范围：服务数、用户数、SLA风险
- 关键时间：发生、接入、预期恢复
- 当前处理人与Copilot分析状态

### 2. 事故上下文面板（左侧）

- **故障对象卡片**：受影响服务/主机/DB/缓存及其状态
- **时间脉络**：告警触发→人工接入→诊断→处置→恢复
- **关联知识**：本产品/跨产品相似案例、SOP、历史根因
- **KG子图**：服务依赖、变更关联、关键路径

### 3. Copilot诊断面板（中央）

- 自动诊断结果（多候选根因+置信度+证据）
- 相似案例推荐
- 与维护的多轮对话框
- 推荐诊断步骤与工具

### 4. 多角色讨论区（右侧）

- 维护/开发/Copilot消息流
- @提及功能
- 关键决策标记
- 聊天转储为公告

### 5. 可执行工具与脚本建议

- 现有审批工具（绿色，可直接执行）
- Copilot生成脚本（黄色，待审批）
- 高危脚本（红色，需开发审批）

### 6. 执行日志与结果反馈

- 工具/脚本执行历史
- 实时进度与结果
- 改善指标反馈
- 后续诊断建议

---

## 完整工作流

`
14:20   维护登入 → 接入故障
        ↓
        Copilot自动诊断（日志+案例+推理）
        ↓
        维护阅读诊断 + 与Copilot对话 + 执行工具1
        ↓
14:30   维护@开发 确认结果
        ↓
        开发进入 → 回复建议
        ↓
        Copilot监听讨论 → 发送总结
        ↓
        维护根据建议继续诊断
        ↓
14:40   Copilot生成脚本 → 维护和开发讨论 → 开发审批
        ↓
        维护执行脚本 → 查看结果
        ↓
14:50   执行修复操作 → 故障消退
        ↓
15:00   标记故障恢复
        ↓
        Copilot启动自动复盘
        ├─ 生成时间线、根因、决策、工具清单
        └─ 形成复盘报告
        ↓
15:10   维护/开发审批报告 → 选择脚本永久化 → 故障关闭
        ↓
        新知识资产入库
`

---

## 技术实现建议

### 前端架构

- React Hooks + Context 管理全局故障状态
- Copilot聊天面板（支持流式输出）
- WebSocket实时推送执行/讨论/诊断更新
- Prism.js代码展示
- ECharts/D3可视化关联与时间线

### 关键组件

`
IncidentHeader
ContextPanel（左）
CopilotPanel（中）
  ├─ DiagnosisCard
  ├─ ChatBox
  └─ CaseRecommendation
DiscussionRoom（右）
ToolsAndScriptsPanel
ExecutionLogPanel
PostmortemModal
`

### API期望

- POST /copilot/diagnose
- POST /copilot/chat
- GET /script/suggest
- POST /script/verify（Dry Run）
- POST /tool/execute
- POST /incident/{id}/discussion
- GET /postmortem/{id}

---

## 设计原则

1. **大模型前置**：自动诊断，而非被动等待
2. **人机协同**：Copilot建议+维护决策+开发确认
3. **可执行优先**：诊断→工具/脚本→执行
4. **透明审计**：置信度、依据、历史全记录
5. **知识循环**：故障→脚本→复盘→资产
6. **跨角色协同**：维护/开发/Copilot同界面消除沟通成本
