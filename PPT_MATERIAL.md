==============================================================================
  PPT-READY MATERIAL: IntelliOps Knowledge Dedup + Aggregation
  Aim: Solve high-frequency alert knowledge duplication via Skill distillation
==============================================================================

---
## Architecture Overview (3 new modules + 2 modified files)

`
run_postmortem_agent()
  |
  |-- 1. KnowledgeDistiller (existing, unchanged)
  |     LLM distills 5 asset types from postmortem
  |
  |-- 2. knowledge_deduplicator [NEW]
  |     |- Semantic dedup (cosine similarity)
  |     |- Merge into existing entries
  |     |- Track frequency per pattern
  |
  |-- 3. DB.upsert_knowledge (existing)
  |
  |-- 4. pattern_aggregator [NEW]
  |     |- LLM batch refinement of high-freq patterns
  |     |- Threshold calibration suggestions
  |     |- Auto-remediation readiness scoring
  |
  |-- 5. skill_updater [NEW]
           |- Inject mature patterns into SKILL.md ref files
           |- Create auto-remediation SKILL.md at readiness >= 70%
`

---
## 5 Asset Types with Specialized Merge Strategies

| Asset Type | Merge Strategy |
|-----------|----------------|
| root_cause_rules | Average confidence, union conditions, append sources |
| sop_templates | Keep longest steps, union unique steps |
| warning_signals | Escalate severity upward, merge sources |
| script_recommendations | Keep longer/more complete code snippet |
| key_learnings | Set-based dedup (unique strings only) |

---
## Configurable Thresholds (env vars, no code changes)

| Variable | Default | Meaning |
|----------|---------|---------|
| KNOWLEDGE_MERGE_THRESHOLD | 0.82 | Cosine >= merge into existing |
| KNOWLEDGE_VARIANT_THRESHOLD | 0.65 | Cosine >= flag as variant |
| KNOWLEDGE_STORE_THRESHOLD | 0.35 | Cosine <= store as new entry |
| KNOWLEDGE_HIGH_FREQ_THRESHOLD | 5 | Incidents >= trigger batch refine |

---
## Refined Pattern Output Schema

| Field | Description |
|-------|-------------|
| canonical_pattern | Merged authoritative pattern (LLM refined) |
| merged_conditions | Deduplicated union of trigger conditions |
| confidence | Weighted average confidence |
| auto_remediation_readiness | 0-1 score for automation viability |
| threshold_calibrations | Monitoring threshold adjustment suggestions |
| cross_service_pattern | Cross-service cascade description |

---
## SKILL Hot-Update Mapping

| Asset Type | Target File |
|-----------|------------|
| root_cause_rules | src/skill/incident-diagnosis/references/root-cause-patterns.md |
| warning_signals | src/skill/incident-diagnosis/references/diagnosis-api.md |
| sop_templates | src/skill/script-operations/references/risk-matrix.md |
| script_recommendations | src/skill/script-operations/references/risk-matrix.md |
| (readiness >= 0.7) | src/skill/auto-xxx/SKILL.md (auto-generated) |

---
## Demo: 6 Incidents, 1 Pattern (Connection Pool Exhaustion)

| Incident | Root Cause | Confidence |
|----------|-----------|-----------|
| inc-001 | Payment gateway DB pool exhausted, peak load | 85% |
| inc-002 | Order service DB pool exhausted, peak traffic | 78% |
| inc-003 | Core accounting pool undersized, batch | 91% |
| inc-004 | Cache service connection leak | 82% |
| inc-005 | API gateway vs backend pool mismatch | 79% |
| inc-006 | Pool not re-tuned after container migration | 88% |

---
## Before vs After Comparison

| Dimension | Traditional Approach | With Skill Dedup System |
|-----------|--------------------|------------------------|
| N same-type incidents | N redundant entries | ~N/3 refined patterns |
| High-freq alert quality | Degrades (noise) | Improves (refinement) |
| AI response to recurring | Loads N similar cases | Loads 1 authoritative pattern |
| Monitoring thresholds | Manual tuning | Auto-generated calibration |
| Knowledge to Skill | Manual copy/paste | Auto hot-update |

---
## Key Design Decisions

1. Non-blocking: Dedup failure does not block postmortem return
2. Dual path: LLM + heuristic fallback (graceful degradation)
3. Incremental: No KB rebuild needed, works from day 1
4. Maturity ladder: raw -> deduped -> merged -> refined -> SKILL
5. Configurable: All thresholds via env vars

---
## Code Stats

| File | Lines | Purpose |
|------|-------|---------|
| knowledge_deduplicator.py | 360 | Semantic dedup + merge + freq tracking |
| pattern_aggregator.py | 310 | LLM + heuristic batch refinement |
| skill_updater.py | 260 | SKILL.md ref injection + auto-skill |
| incident_pipeline.py (mod) | +45 | Integration hook |
| db.py (mod) | +12 | list_knowledge + delete_knowledge list |
| Total | ~987 | 3 new modules + 2 modified files |

==============================================================================
  END OF PPT MATERIAL
==============================================================================