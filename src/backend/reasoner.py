"""
IncidentReasoner — multi-stage chain-of-thought root cause reasoning.

Stage 1: Symptom classification (what kind of failure?)
Stage 2: Dependency & blast-radius analysis (what's affected?)
Stage 3: Change & alert correlation (what changed recently?)
Stage 4: Root cause synthesis (ranked hypotheses + evidence chains)

Falls back to rule-based reasoning when LLM is unavailable or parsing fails.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .llm_client import LLMClient, LLMResponse


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
你是一个 SRE 故障根因推理专家。你需要按照结构化思维链分析故障，最终输出 JSON。

分析框架（在思维中完成，不输出）：
1. 故障现象分类：延迟？错误率？资源耗尽？依赖故障？
2. 影响面分析：哪些服务/主机/依赖受影响？依赖链是什么？
3. ⭐ 上下文系统分析：检查上游系统的变更、下游系统的影响、共享依赖的异常
   - 上游系统（会影响本服务的系统）：优先检查它们的变更记录，上游变更常常是根因
   - 下游系统（受本服务影响的系统）：检查是否出现级联故障征兆
   - 共享依赖：多个服务共享的 DB/MQ/缓存是否存在异常
4. 变更关联：不仅检查直接关联变更，还要检查上游系统的变更窗口
5. 根因排序：综合证据，对候选根因按置信度排序。

⭐ 上下文系统工具推荐原则：
- 如果上游系统是数据库 → 建议检查数据库连接池、慢查询、锁等待
- 如果上游系统是消息队列 → 建议检查队列积压、消费延迟、死信队列
- 如果上游系统是缓存 → 建议检查命中率、内存使用、连接数
- 如果上游系统是第三方接口 → 建议探测接口可用性和响应时间
- 在 detail 字段中说明为什么要检查这些上下文系统

输出要求：
- 严格输出 JSON，不要包含任何额外文本、解释或 markdown 代码块标记。
- 每个 candidate_root_cause 必须包含 cause、confidence(0-1)、detail、evidence_items(字符串数组)。
- evidence_items 应包含来自上下游系统的证据线索（如有）。
- reasoning_chain 用简短文字描述从现象到根因的推导路径。
- confidence_summary 取所有候选置信度的加权平均。
"""

USER_PROMPT_TEMPLATE = """\
## 事件信息
{incident_json}

## 知识图谱上下文（含上下游系统与变更）
{kg_json}

⭐ 重要提示：
- "upstream_changes" 是上游系统的变更，它们是根因的高概率来源，请优先分析
- "downstream_changes" 是下游系统的变更，可能揭示级联影响
- "dependency_chain" 展示了服务间依赖关系，请据此推断故障传播路径
- 请在 evidence_items 中引用上下游系统的具体证据

请按分析框架推理，输出 JSON。"""


# ---------------------------------------------------------------------------
# IncidentReasoner
# ---------------------------------------------------------------------------

class IncidentReasoner:
    """Multi-stage root cause reasoner with LLM + rule-based fallback."""

    @staticmethod
    def _build_system_prompt() -> str:
        return SYSTEM_PROMPT

    @staticmethod
    def _build_user_prompt(incident: Dict[str, Any], kg_context: Dict[str, List[Dict[str, Any]]]) -> str:
        return USER_PROMPT_TEMPLATE.format(
            incident_json=json.dumps(incident, ensure_ascii=False, indent=2),
            kg_json=json.dumps(kg_context, ensure_ascii=False, indent=2),
        )

    @staticmethod
    def _extract_json(text: str) -> Dict[str, Any]:
        """Robust JSON extraction — tries direct parse, then bracketed extraction."""
        text = text.strip()

        # Remove markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Drop first line (```json or ```) and last line (```)
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            text = "\n".join(lines).strip()

        # Direct parse attempt
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Bracket-matching extraction
        start = text.find("{")
        if start >= 0:
            brace_level = 0
            for i, ch in enumerate(text[start:], start=start):
                if ch == "{":
                    brace_level += 1
                elif ch == "}":
                    brace_level -= 1
                    if brace_level == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            break

        raise ValueError("未能从 LLM 响应中找到有效 JSON 对象")

    @staticmethod
    def _validate_reasoning_output(parsed: Dict[str, Any], incident_id: str) -> Dict[str, Any]:
        """Ensure the parsed output has all required fields."""
        if not parsed.get("incident_id"):
            parsed["incident_id"] = incident_id
        if not isinstance(parsed.get("candidate_root_causes"), list):
            parsed["candidate_root_causes"] = []
        if not isinstance(parsed.get("evidence"), list):
            parsed["evidence"] = []
        if not isinstance(parsed.get("reasoning_steps"), list):
            parsed["reasoning_steps"] = []
        if not isinstance(parsed.get("reasoning_chain"), str):
            parsed["reasoning_chain"] = ""

        # Normalize each candidate
        for cause in parsed["candidate_root_causes"]:
            if not isinstance(cause.get("evidence_items"), list):
                cause["evidence_items"] = []
            if not isinstance(cause.get("confidence"), (int, float)):
                cause["confidence"] = 0.5
            cause["confidence"] = max(0.0, min(1.0, float(cause["confidence"])))

        # Recalculate confidence_summary
        confidences = [c.get("confidence", 0) for c in parsed["candidate_root_causes"]]
        parsed["confidence_summary"] = round(sum(confidences) / max(len(confidences), 1), 2)

        return parsed

    # ------------------------------------------------------------------
    # Rule-based fallback (local, no LLM)
    # ------------------------------------------------------------------

    @staticmethod
    def _rule_based_fallback(
        incident: Dict[str, Any], kg_context: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, Any]:
        summary = incident.get("summary", "")
        related_alerts = incident.get("related_alerts", [])
        related_changes = incident.get("related_changes", [])
        affected_services = incident.get("affected_services", [])
        alert_nodes = kg_context.get("alerts", [])
        change_nodes = kg_context.get("changes", [])
        service_nodes = kg_context.get("services", [])

        candidates: List[Dict[str, Any]] = []
        evidence: List[str] = []
        steps: List[str] = []

        if "延迟" in summary or "慢" in summary or "latency" in summary.lower():
            candidates.append({
                "cause": "服务响应延迟 — 可能由下游资源瓶颈、连接池耗尽或网络抖动导致",
                "confidence": 0.78,
                "detail": "事件摘要包含延迟类描述，优先排查数据库连接池、慢查询和网络链路。",
                "evidence_items": ["摘要含延迟关键词", "需补充 P99 延迟趋势和连接池指标"],
            })
            steps.append("【现象分类】故障表现为延迟升高，归类为性能退化型故障。")
            evidence.append("事件摘要包含延迟相关描述。")

        if related_alerts:
            alert_names = [node.get("name", aid) for node in alert_nodes for aid in related_alerts if node.get("id") == aid] or related_alerts
            candidates.append({
                "cause": "监控告警触发的系统异常 — 需关联告警详情确定触发源",
                "confidence": 0.65,
                "detail": f"关联告警：{alert_names}，建议核对告警时间线与故障窗口的重叠度。",
                "evidence_items": [f"相关告警: {alert_names}"],
            })
            steps.append("【告警关联】发现相关告警记录，正在匹配时间窗口。")
            evidence.append(f"相关告警：{alert_names}")

        if related_changes:
            change_names = [node.get("name", cid) for node in change_nodes for cid in related_changes if node.get("id") == cid] or related_changes
            candidates.append({
                "cause": "近期变更引入的配置或部署异常 — 变更窗口与故障时间高度重叠",
                "confidence": 0.72,
                "detail": f"可疑变更：{change_names}，建议审查变更内容并评估回滚可行性。",
                "evidence_items": [f"关联变更: {change_names}"],
            })
            steps.append("【变更关联】发现窗口内变更，将其列为高优先级排查对象。")
            evidence.append(f"关联变更：{change_names}")

        if affected_services:
            service_names = [node.get("name", sid) for node in service_nodes for sid in affected_services if node.get("id") == sid] or affected_services
            candidates.append({
                "cause": "核心服务依赖链异常 — 上游或下游依赖可能导致级联故障",
                "confidence": 0.70,
                "detail": f"受影响服务：{service_names}，建议绘制依赖拓扑，定位级联起点。",
                "evidence_items": [f"影响服务: {service_names}"],
            })
            steps.append("【依赖分析】受影响服务已识别，正在分析依赖链路。")
            evidence.append(f"影响服务：{service_names}")

        if not candidates:
            candidates.append({
                "cause": "信息不足，无法确定高置信度根因 — 建议补充日志、指标和变更记录",
                "confidence": 0.35,
                "detail": "当前仅有事件摘要，缺少日志片段、性能指标、变更详情等关键上下文。",
                "evidence_items": ["事件信息有限"],
            })
            steps.append("【信息不足】当前证据不足以支持高置信度推理。")
            evidence.append("事件摘要、关联变更或告警信息不足。")

        return {
            "incident_id": incident.get("incident_id"),
            "candidate_root_causes": candidates,
            "reasoning_steps": steps,
            "reasoning_chain": " → ".join(s.replace("【", "").replace("】", ": ").rstrip("。") for s in steps),
            "evidence": evidence,
            "confidence_summary": round(sum(c["confidence"] for c in candidates) / len(candidates), 2),
            "method": "rule_based",
        }

    # ------------------------------------------------------------------
    # Main entry point (async)
    # ------------------------------------------------------------------

    @staticmethod
    async def infer_root_causes(
        incident: Dict[str, Any],
        kg_context: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """Run multi-stage root cause reasoning.

        Returns dict with keys:
        - incident_id
        - candidate_root_causes: [{cause, confidence, detail, evidence_items}]
        - reasoning_steps: [str]
        - reasoning_chain: str
        - evidence: [str]
        - confidence_summary: float
        - method: 'llm' | 'rule_based'
        """
        client = LLMClient()

        if client.provider in ("openai", "anthropic", "ollama"):
            print(f"[Reasoner] Using LLM provider: {client.provider}")
            system = IncidentReasoner._build_system_prompt()
            user = IncidentReasoner._build_user_prompt(incident, kg_context)

            try:
                response: LLMResponse = await client.infer(
                    prompt=user,
                    system=system,
                    json_mode=(client.provider == "openai"),  # native JSON mode for OpenAI
                    temperature=0.0,
                    max_tokens=2048,
                )
                parsed = IncidentReasoner._extract_json(response.text)
                result = IncidentReasoner._validate_reasoning_output(parsed, incident.get("incident_id", ""))
                result["method"] = "llm"
                result["model"] = response.model
                result["latency_ms"] = response.latency_ms
                print(f"[Reasoner] LLM reasoning complete ({response.latency_ms:.0f}ms, {response.usage.total_tokens} tokens)")
                return result
            except (ValueError, RuntimeError) as exc:
                # LLM failed or parsing failed — fall back to rules
                print(f"[Reasoner] LLM failed, falling back to rule-based: {exc}")
                result = IncidentReasoner._rule_based_fallback(incident, kg_context)
                result["llm_error"] = str(exc)[:200]
                return result

        # No LLM configured — use rules
        print("[Reasoner] No LLM provider configured, using rule-based reasoning")
        return IncidentReasoner._rule_based_fallback(incident, kg_context)
