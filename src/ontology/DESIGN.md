# 本体设计（Ontology）

## 当前实现（2026-06-06）

> **实际采用轻量 JSON Schema 校验**，定义实体/属性/关系规范。验证逻辑已独立为 `validator.py`。

### 实现文件

| 文件 | 位置 | 功能 |
|------|------|------|
| `validator.py` | `src/ontology/` | `ONTOLOGY_SCHEMA` 定义 + `validate_payload()` 校验函数 |
| `sample_ontology.jsonld` | `src/ontology/` | 示例 JSON-LD 本体文件 |
| `__init__.py` | `src/ontology/` | 模块入口 |

### API 端点

| 端点 | 说明 |
|------|------|
| `GET /ontology` | 返回示例 JSON-LD 本体 |
| `GET /ontology/version` | 返回版本号 `v0.1` |
| `GET /ontology/schema` | 返回验证规则 |
| `POST /ontology/validate` | 校验 JSON-LD 载荷 |

## 实体与关系

### 实体集
`Incident`, `Alert`, `Service`, `Host`, `Change`, `WorkOrder`, `Action`, `Person`, `SOP`

### 关系模式
- `Incident` — `related_to` → `Alert`
- `Service` — `depends_on` → `Service` / `Host`
- `Change` — `affects` → `Service` / `Host`
- `Action` — `used_in` → `SOP` / `Incident`

## 未来演进

- Ontology CRUD 端点（创建/更新/删除实体和关系定义）
- 版本演进管理（v0.1 → v0.2 变更日志）
- OWL 导出供外部推理引擎使用

