---
name: git-incident-docs
description: >
  管理故障相关文档的版本控制。触发词：提交、commit、版本、分支、PR、发布复盘、存档、备份报告。使用场景：需要将复盘报告纳入版本控制时、需要管理SOP模板版本时、需要归档故障文档时。
user-invocable: true
---
# 故障文档版本管理

> 改编自通用 Git Workflow Skill，针对故障文档管理定制。

## 何时使用

- 复盘报告需要提交到 Git 仓库归档
- SOP 模板需要版本控制和变更历史
- 脚本需要纳入代码仓库管理
- 需要为故障创建专门的文档分支

## 文档分类与存储路径

| 文档类型 | 存储路径 | 命名规范 |
|---------|---------|---------|
| 复盘报告 | `docs/postmortems/` | `YYYY-MM-DD-{{incident_id}}-{{summary}}.md` |
| SOP 模板 | `docs/sops/` | `{{category}}-{{title}}.md` |
| 诊断脚本 | `scripts/diagnosis/` | `check_{{purpose}}.sh` |
| 知识资产 | `docs/knowledge/` | `rule_{{pattern}}.md` |

## 标准工作流

### 场景 1：提交复盘报告

```
1. git checkout -b postmortem/{{incident_id}}
2. 将复盘报告保存到 docs/postmortems/
3. git add docs/postmortems/{{filename}}.md
4. git commit -m "postmortem: {{incident_id}} - {{一句话摘要}}"
5. git push origin postmortem/{{incident_id}}
6. 创建 PR 供团队审核
```

### 场景 2：更新 SOP 模板

```
1. git checkout -b sop/{{sop_title}}
2. 修改 docs/sops/{{filename}}.md
3. git commit -m "sop: update {{sop_title}} based on incident {{incident_id}}"
4. 创建 PR，在描述中引用复盘报告链接
```

### 场景 3：归档诊断脚本

```
1. 确认脚本已验证可用（risk_level: low 或 已通过审批）
2. git checkout -b script/{{script_name}}
3. 将脚本保存到 scripts/diagnosis/
4. git commit -m "script: add {{script_name}} from incident {{incident_id}}"
5. 创建 PR，注明脚本来源和验证结果
```

## Commit 信息规范

```
<type>: <简短描述>

来源: incident {{incident_id}}
根因: {{根因摘要}}
验证: {{验证方式}}
```

类型（type）：
- `postmortem`：复盘报告
- `sop`：标准操作流程
- `script`：诊断/处置脚本
- `rule`：根因规则
- `knowledge`：通用知识条目

## 注意事项

- 提交前检查是否包含敏感信息（IP、密码、密钥）
- 复盘报告中的内部沟通内容应先脱敏再提交
- 脚本提交前确认已通过 dry-run 验证
