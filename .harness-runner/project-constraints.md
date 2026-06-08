# Harness 项目约束

> Last Updated: 2026-06-06

## Technology Summary
- **后端**: Python 3.12+ / FastAPI / uvicorn / aiosqlite (SQLite WAL)
- **前端**: JavaScript 原生 (原型阶段), React 重构待 B7
- **LLM**: OpenAI >=1.0.0 / Anthropic / Ollama (httpx), 支持流式 SSE
- **向量检索**: sentence-transformers + FAISS (可选), TF-IDF 回退
- **数据加载**: pandas / openpyxl / xlrd / python-docx

## Build Commands
- `pip install -r requirements.txt`
- `docker-compose up` (生产部署)

## Verification Commands
- `python -c "from src.backend.app import app; print('OK')"`
- `uvicorn src.backend.app:app --reload --host 0.0.0.0 --port 8000` (开发模式运行)

## Test Commands
- `pytest src/ --ignore=src/ui/` (测试套件待建设)

## Lint Commands
- `ruff check src/backend/` (推荐, 快速)
- `pylint src/backend/ --disable=C0114,C0115,C0116` (完整检查)

## Style Rules
- 模块职责单一：一个 .py 文件只负责一个明确的功能领域，例如 reasoner.py 只管推理，copilot.py 只管对话
- `app.py` 只包含路由注册和全局初始化，业务逻辑提取到独立模块（如 log_analyzer.py, credibility.py）
- Pydantic 模型统一放在 `models.py`，不在 `app.py` 中定义模型类
- 全链路使用 async/await（FastAPI + aiosqlite + LLM 调用全部异步）
- 中英文混用规范：面向用户的输出使用中文（日志、API 响应、Skill 正文），代码标识符（变量名、函数名）使用英文
- SKILL.md 文件使用中文正文 + YAML frontmatter，遵循 VS Code Copilot Skill 规范

## Git Rules
- 提交标题和描述必须使用中文
- 提交粒度：每个逻辑变更一个 commit，避免超大 commit（如"全部 Person A 模块"）
- Person A（认知引擎）和 Person B（数据平台）在同一文件上的变更分别提交

## Architecture Rules
- 可复用逻辑必须放在专用模块中，禁止跨文件复制粘贴代码
- 入口点（app.py）保持薄层：只做路由注册和全局初始化
- 当前 src/ 子目录：backend, harness, kg, ontology, skill, ui
- `src/backend/` 采用扁平模块结构（16 个 .py 文件），当文件数超过 30 时考虑拆分子目录
- KG 图查询逻辑集中在 `knowledge_graph.py`，不散落在 `app.py`
- Ontology 校验逻辑集中在 `src/ontology/validator.py`，`app.py` 只做 import
- Skill 文件放在 `src/skill/<name>/SKILL.md`，每个 Skill 自包含（含 references/ 子目录）
- 真实数据文件放在 `data/` 目录，通过 `data_service.py` 统一加载，禁止在业务代码中硬编码文件路径
- Harness 模块已吸收：执行逻辑在 `app.py` 的 `/script/*` 和 `/action/*` 端点中，不需要独立 Harness 模块

## Allowed Paths (可修改的目录)
- `src/**` — 全部源代码
- `docs/**` — 设计文档
- `data/**` — 数据文件 (运行时只读, 手动添加)
- `src/backend/**` — 后端模块
- `src/skill/**` — Copilot Skill 文件
- `src/ontology/**` — 本体定义与校验
- `src/kg/**` — 知识图谱示例数据
- `src/harness/**` — 执行框架设计文档 (已吸收)
- `src/ui/**` — 前端原型

## Forbidden Paths (不可修改的目录)
- `.idea/**` — IDE 自动生成, 不在版本控制意图内
- `.git/**` — Git 内部文件

## Reuse Hints (复用提示)
- **调用 LLM** → 必须通过 `llm_client.py`，禁止在其他模块中直接 import openai / anthropic / httpx
- **数据库操作** → 必须通过 `db.py`，禁止在其他模块中直接使用 aiosqlite
- **Pydantic 模型** → 从 `models.py` 导入，禁止在其他文件中重复定义相同的请求/响应模型
- **图查询** → 复用 `knowledge_graph.py` 的邻接表 + BFS 方法，不要自己在 app.py 中写 BFS
- **日志分析** → 复用 `log_analyzer.py` 的模式库和 error-patterns.md，不要在其他地方重复定义错误正则
- **向量检索** → 复用 `vector_search.py` 的单例 `get_vector_search()`
- **WebSocket 广播** → 复用 `websocket_manager.py` 的 `manager.broadcast()`
- **前后端 API 契约** → 参考 `src/backend/README.md` 中的端点列表，新增端点前先检查是否已有类似功能

## Delivery Checklist (交付前检查)
- [ ] 所有 .py 文件导入无错误：`python -c "from src.backend.app import app"`
- [ ] 新端点已添加 Pydantic 模型到 `models.py`（如需）
- [ ] 新端点已添加到 `app.py` 根路由列表 `/` 中
- [ ] 新模块已在对应的 `DESIGN.md` 中记录功能说明
- [ ] 需求变更已更新 `prd.json` 的 userStories 或 architecture
- [ ] 提交使用中文 commit message
- [ ] 如修改模块边界，已重新生成 `project-constraints.generated.json`
