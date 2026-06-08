# 诊断 API 参考

## 核心端点

### POST /copilot/diagnose

启动自动诊断会话。

**请求**：
```json
{
  "incident_id": "inc-1",
  "user_id": "ui-user"
}
```

**响应关键字段**：
```json
{
  "diagnosis_id": "diag-abc123",
  "candidate_root_causes": [
    {
      "cause": "根因描述",
      "confidence": 0.78,
      "confidence_level": "high",
      "evidence_chain": ["证据项1", "证据项2"],
      "similar_incidents": [{"incident_id": "...", "similarity_score": 3}],
      "credibility": {
        "adjusted_confidence": 0.65,
        "credibility_level": "medium",
        "factors": {
          "evidence_quality": 0.8,
          "source_reliability": 0.9,
          "contradiction_penalty": 0.92
        }
      }
    }
  ],
  "log_analysis": {
    "summary": "过去30分钟检测到 7 条异常日志...",
    "key_events": [...],
    "anomalies": [...],
    "correlations": [
      {
        "sources": ["app/payment", "db/postgres"],
        "pattern_description": "应用层连接超时与数据库层错误同时出现...",
        "confidence": 0.82
      }
    ]
  },
  "initial_recommendations": [
    {
      "step": "检查数据库连接池状态",
      "tools": ["act-001"],
      "rationale": "连接池耗尽是最常见的延迟根因",
      "risk_assessment": {
        "risk_level": "low",
        "requires_approval": false
      }
    }
  ],
  "evidence_chain": [
    {"source": "incident", "type": "事件数据", "reliability": "high"},
    {"source": "log_analyzer", "type": "日志分析", "reliability": "medium"}
  ],
  "confidence_summary": 0.71
}
```

### POST /copilot/chat

多轮诊断对话。

**请求**：
```json
{
  "incident_id": "inc-1",
  "diagnosis_id": "diag-abc123",
  "user_id": "ui-user",
  "message": "我已经查了连接池，活跃连接450/500"
}
```

**响应关键字段**：
```json
{
  "response": "收到！连接池接近上限...",
  "updated_root_causes": [...],
  "suggested_actions": [
    {
      "action": "检查慢查询",
      "type": "query",
      "risk": "low",
      "rationale": "慢查询可能阻塞连接"
    }
  ],
  "follow_up_question": "需要我生成慢查询检查脚本吗？",
  "confidence_trend": "improving",
  "key_findings": ["连接池接近上限"]
}
```

### GET /incident/{id}/related-cases

获取相似历史案例。

**响应**：
```json
{
  "cases": [
    {
      "incident_id": "inc-old-1",
      "summary": "类似故障摘要",
      "similarity_score": 3,
      "root_cause": "历史根因",
      "resolution_steps": ["步骤1", "步骤2"],
      "scripts_used": ["script-1"]
    }
  ]
}
```

`similarity_score` 含义：1-2=低相似，3-4=中相似，5+=高相似。

## 字段解读指南

| 字段 | 含义 | 何时关注 |
|------|------|---------|
| `credibility_level: high` | 可信度高 | 可直接作为决策依据 |
| `credibility_level: medium` | 需验证 | 建议收集更多证据 |
| `credibility_level: low` | 不可靠 | 必须补充数据后才能使用 |
| `confidence_trend: improving` | 方向正确 | 继续当前排查方向 |
| `confidence_trend: declining` | 方向错误 | 切换排查假设 |
| `log_analysis.correlations[].confidence > 0.8` | 强关联 | 优先排查关联组合 |
