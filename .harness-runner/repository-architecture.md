# Repository Architecture

## Source of Truth
- PRD: prd.json
- Repository architecture: .harness-runner/repository-architecture.md
- Generated constraints: .harness-runner/project-constraints.generated.json
- Editable constraints: .harness-runner/project-constraints.md

## Repository Summary
- Repository name: IntelliOps
- Language: Python (FastAPI backend), JavaScript (vanilla UI prototype)
- Purpose: 大模型驱动的故障应急认知原型 — 验证 LLM 在故障诊断、根因推理、协同应急、自动复盘中的认知能力
- Team model: 两人并行 (Person A 认知引擎, Person B 数据平台)

## Repository Structure

### Top-Level Directories
| Directory | Purpose | Stability |
|-----------|---------|-----------|
| `.github/` | GitHub Copilot Skills (legacy, migrated to src/skill/) | Deprecated |
| `.idea/` | PyCharm project settings | Auto-generated |
| `.harness-runner/` | Project constraints and architecture docs | Stable |
| `data/` | 真实银行数据 (Excel/Word) — 告警、系统关系、应用报表、复盘报告 | Stable (read-only at runtime) |
| `docs/` | 架构/数据模型/工作流设计文档 | Stable (design reference) |
| `src/` | 全部源代码 | Active development |

### Source Areas (`src/`)
| Directory | Layer | Purpose | Key Files |
|-----------|-------|---------|-----------|
| `src/backend/` | 全部后端 | FastAPI 单体应用 (16 .py 模块) | `app.py`, `db.py`, `models.py`, `reasoner.py`, `copilot.py` |
| `src/skill/` | 能力层 | 9 个 VS Code Copilot SKILL.md 文件 | `incident-diagnosis/SKILL.md` 等 |
| `src/ontology/` | 知识层 | 本体 Schema 定义与校验 | `validator.py`, `sample_ontology.jsonld` |
| `src/kg/` | 知识层 | 示例 KG 数据 | `sample_kg.json` |
| `src/harness/` | 已吸收 | 执行框架设计文档 (逻辑已并入 backend) | `DESIGN.md`, `sample_actions.json` |
| `src/ui/` | 应用层 | 前端原型 (单 HTML) | `index.html` (~900 行) |

## Module Boundaries

### Core Principle
- **Keep reusable logic in dedicated modules** — do not duplicate across the codebase
- **Keep entrypoints thin** — `app.py` should only contain route wiring and global init
- **Prefer extending existing modules** over creating parallel files for already-owned concerns

### Module Ownership
| Module | Owner | Should NOT be duplicated in |
|--------|-------|---------------------------|
| `db.py` | SQLite persistence | `app.py` (no direct dict/list manipulation) |
| `models.py` | All Pydantic request/response types | `app.py` (import only) |
| `llm_client.py` | LLM invocation (all providers) | Any other file (always go through this) |
| `reasoner.py` | Root cause reasoning | `copilot.py`, `fault_diagnosis.py` |
| `knowledge_graph.py` | Graph queries (adjacency + BFS) | `app.py` (KG helpers already extracted) |
| `ontology/validator.py` | Ontology schema + validation | `app.py` (already extracted) |
| `state_machine.py` | Investigation state quadrants | `app.py` |
| `websocket_manager.py` | WebSocket connection groups | `app.py` |

### Extension Points
- `src/skill/*/SKILL.md` — Add new Copilot skills here without changing backend code
- `src/backend/models.py` — Add new Pydantic models for new endpoints
- `data/` — Add new Excel/Word data files; picked up by `data_service.py`

## Change Surface Guidance

### Allowed Paths (active development)
- `src/**` — All source code
- `docs/**` — Design documentation
- `data/**` — Data files (read-only at runtime, added manually)

### Forbidden Paths (do not modify)
- `.idea/` — IDE auto-generated, not in version control intent
- `.git/` — Git internals

### Stability Notes
- `src/backend/app.py` — Route definitions stable; add new routes, avoid restructuring existing
- `src/backend/models.py` — Append-only; remove models only when corresponding endpoints deleted
- `src/skill/*/SKILL.md` — Self-contained; each SKILL.md is independently loadable
- `prd.json` — Update when user stories or architecture layers change

## PRD Alignment
- All 6 user stories (US-01 to US-06) map to existing backend endpoints
- Architecture follows the 4-layer model: Data → Knowledge → Capability → Application
- Integration points documented in prd.json `integrationPoints`
- Person A (cognitive) and Person B (data) module boundaries reflected in `src/backend/` flat layout
- Harness module absorbed: execution logic lives in `app.py` `/script/*` and `/action/*` endpoints
- Skill module delivered as VS Code Copilot SKILL.md files under `src/skill/`

## Constraint Regeneration Guidance
- Rebuild `.harness-runner/project-constraints.generated.json` from `prd.json` and this document when:
  - New modules are added to `src/backend/` or `src/` subdirectories
  - Architecture layers change (e.g., microservice split)
  - User stories are added/removed in prd.json
  - Integration points change
- The JSON `sourceOfTruth` block must always point back to `prd.json` and this document
- When this document changes module boundaries or allowed paths, update `architectureRules`, `allowedPaths`, `forbiddenPaths`, `reuseHints`, and `deliveryChecklist` in the JSON
- After regeneration, update `story-status.json` entry `project-constraints-init` to `completed` and bump the timestamp
