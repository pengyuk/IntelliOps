"""
Log Analyzer — intelligent log summarization, anomaly detection & cross-source correlation.

Supports:
- Simulated log generation (prototype phase — no real log pipeline yet)
- LLM-powered analysis: summarization, anomaly pattern recognition, correlation
- Rule-based fallback: regex pattern matching, frequency analysis
- Structured output for injection into the root-cause reasoning pipeline
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .llm_client import LLMClient, LLMResponse

# ---------------------------------------------------------------------------
# Simulated log templates (prototype — replace with real ETL in production)
# ---------------------------------------------------------------------------

_LOG_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
    "latency": [
        {"level": "ERROR", "message": "timeout waiting for DB connection after 5000ms", "source": "app/payment-service"},
        {"level": "WARN", "message": "slow query detected: SELECT * FROM orders WHERE status='PENDING' took 3200ms", "source": "db/postgres"},
        {"level": "ERROR", "message": "connection pool exhausted: active=450, max=500, pending=37", "source": "app/payment-service"},
        {"level": "WARN", "message": "retry exhausted for payment callback to gateway", "source": "app/payment-service"},
        {"level": "ERROR", "message": "circuit breaker OPEN for downstream inventory-service after 5 failures", "source": "app/payment-service"},
        {"level": "WARN", "message": "GC pause exceeded threshold: 1200ms (young gen)", "source": "host/payment-host-01"},
        {"level": "INFO", "message": "health check failed for /actuator/health: status=DOWN", "source": "k8s/payment-pod-3"},
        {"level": "ERROR", "message": "OutOfMemoryError: Java heap space in thread http-nio-8080-exec-47", "source": "host/payment-host-01"},
    ],
    "error_rate": [
        {"level": "ERROR", "message": "HTTP 500 Internal Server Error at /api/orders/create", "source": "app/order-service"},
        {"level": "ERROR", "message": "NullPointerException at OrderController.java:142", "source": "app/order-service"},
        {"level": "WARN", "message": "failed to deserialize request body: unexpected EOF", "source": "app/order-service"},
        {"level": "ERROR", "message": "connection refused to inventory-service:8080", "source": "app/order-service"},
        {"level": "WARN", "message": "fallback cache hit ratio dropped to 0.3 from 0.95", "source": "app/order-service"},
        {"level": "ERROR", "message": "too many open files (ulimit=1024) for process java", "source": "host/order-host-02"},
        {"level": "WARN", "message": "disk I/O latency spike: avg=450ms (normal=5ms)", "source": "host/order-host-02"},
    ],
    "resource_exhaustion": [
        {"level": "ERROR", "message": "disk space critical: /data 92% used (5.1GB remaining)", "source": "host/db-host-01"},
        {"level": "WARN", "message": "CPU throttled: container exceeded limit 2000m for 120s", "source": "k8s/payment-pod-1"},
        {"level": "ERROR", "message": "OOMKilled: container payment-service memory limit 512Mi reached", "source": "k8s/payment-pod-2"},
        {"level": "WARN", "message": "swap usage increased to 2.3GB from 100MB baseline", "source": "host/payment-host-01"},
        {"level": "ERROR", "message": "too many connections: max_connections=100 reached", "source": "db/postgres"},
        {"level": "WARN", "message": "connection pool wait time avg=2500ms (normal=15ms)", "source": "app/payment-service"},
    ],
    "change_related": [
        {"level": "ERROR", "message": "ClassNotFoundException: com.payment.NewConnectionPool", "source": "app/payment-service"},
        {"level": "WARN", "message": "configuration key 'db.pool.max' changed from 200 to 50 at 09:45", "source": "app/payment-service"},
        {"level": "ERROR", "message": "SQLException: FATAL: remaining connection slots are reserved for superuser", "source": "db/postgres"},
        {"level": "WARN", "message": "deployment v2.3.1 rolled out at 09:42, previous version v2.3.0", "source": "k8s/deployment-controller"},
    ],
}


def _pick_template(incident: Dict[str, Any]) -> str:
    """Heuristically pick the best-matching log template based on incident summary."""
    summary = (incident.get("summary", "") + " " + incident.get("status", "")).lower()
    if any(w in summary for w in ("延迟", "慢", "latency", "timeout", "slow")):
        return "latency"
    if any(w in summary for w in ("失败", "错误", "error", "fail", "500", "502", "503")):
        return "error_rate"
    if any(w in summary for w in ("资源", "耗尽", "内存", "cpu", "disk", "exhaust", "oom")):
        return "resource_exhaustion"
    if any(w in summary for w in ("变更", "部署", "change", "deploy", "release")):
        return "change_related"
    return "latency"  # default


def generate_simulated_logs(incident: Dict[str, Any], count: int = 8) -> List[Dict[str, Any]]:
    """Generate simulated log entries for a given incident (prototype only)."""
    template_key = _pick_template(incident)
    templates = _LOG_TEMPLATES.get(template_key, _LOG_TEMPLATES["latency"])
    # Cycle through templates if count > len(templates)
    logs = []
    for i in range(min(count, len(templates))):
        entry = dict(templates[i])
        entry["timestamp"] = f"2026-06-01T10:{i:02d}:00Z"
        logs.append(entry)
    return logs


# ---------------------------------------------------------------------------
# LLM prompt templates for log analysis
# ---------------------------------------------------------------------------

LOG_ANALYSIS_SYSTEM = """\
你是一个 SRE 日志分析专家。你需要分析日志片段并输出结构化 JSON。

分析要点：
1. 关键错误事件摘要（按严重程度排序）
2. 异常模式识别（与正常基线对比的频率变化、新错误类型）
3. 跨源关联（应用日志 + 中间件 + 主机 + K8s 事件之间的因果链）

输出要求：
- 严格输出 JSON，不要包含任何额外文本。
- summary: 1-2 句中文概述
- key_events: 按时间排序的关键事件（每条含 timestamp, level, source, message, significance）
- anomalies: 识别的异常模式（含 pattern, evidence_count, severity, baseline_comparison）
- correlations: 跨源关联发现（含 sources, pattern_description, confidence）
- error_categories: 错误类型分类统计（含 category, count, percentage）
"""

LOG_ANALYSIS_USER = """\
## 事件上下文
事件摘要: {summary}
受影响服务: {services}
关联告警: {alerts}
关联变更: {changes}

## 日志片段
{logs_json}

请分析上述日志并输出 JSON。"""


# ---------------------------------------------------------------------------
# Rule-based patterns
# ---------------------------------------------------------------------------

_ERROR_PATTERNS = [
    (re.compile(r"timeout|timed?\s*out", re.IGNORECASE), "超时/Timeout", "high"),
    (re.compile(r"connection\s*(pool|refused|reset|exhausted)", re.IGNORECASE), "连接池/连接异常", "high"),
    (re.compile(r"out\s*of\s*memory|oom|heap\s*space", re.IGNORECASE), "内存耗尽/OOM", "critical"),
    (re.compile(r"slow\s*query|slow\s*log", re.IGNORECASE), "慢查询", "medium"),
    (re.compile(r"circuit\s*breaker", re.IGNORECASE), "熔断/Circuit Breaker", "high"),
    (re.compile(r"null\s*pointer|NullPointerException", re.IGNORECASE), "空指针/NPE", "high"),
    (re.compile(r"class\s*not\s*found|ClassNotFoundException", re.IGNORECASE), "类加载/部署异常", "high"),
    (re.compile(r"disk|I/O|ulimit|too\s*many\s*open\s*files", re.IGNORECASE), "资源限制/磁盘IO", "critical"),
    (re.compile(r"gc\s*pause|GC\s*(pause|overhead)", re.IGNORECASE), "GC异常", "medium"),
    (re.compile(r"cpu\s*throttl|OOMKilled", re.IGNORECASE), "容器资源限制", "critical"),
]


def _rule_based_analyze(logs: List[Dict[str, Any]], incident: Dict[str, Any]) -> Dict[str, Any]:
    """Fast rule-based log analysis without LLM."""
    key_events: List[Dict[str, Any]] = []
    anomalies: List[Dict[str, Any]] = []
    error_categories: Dict[str, int] = {}

    for entry in logs:
        msg = entry.get("message", "")
        level = entry.get("level", "INFO")

        # Classify every ERROR/WARN
        if level in ("ERROR", "WARN", "CRITICAL"):
            matched = False
            for pattern, category, severity in _ERROR_PATTERNS:
                if pattern.search(msg):
                    error_categories[category] = error_categories.get(category, 0) + 1
                    if level == "ERROR" or severity in ("critical", "high"):
                        key_events.append({
                            "timestamp": entry.get("timestamp", ""),
                            "level": level,
                            "source": entry.get("source", ""),
                            "message": msg[:120],
                            "significance": severity,
                            "category": category,
                        })
                    matched = True
                    break
            if not matched:
                error_categories["其他/Unknown"] = error_categories.get("其他/Unknown", 0) + 1
                if level == "ERROR":
                    key_events.append({
                        "timestamp": entry.get("timestamp", ""),
                        "level": level,
                        "source": entry.get("source", ""),
                        "message": msg[:120],
                        "significance": "medium",
                        "category": "其他/Unknown",
                    })

    # Build anomaly summary from categories
    total_errors = sum(error_categories.values())
    for category, count in sorted(error_categories.items(), key=lambda x: -x[1]):
        severity = "medium"
        for _, cat, sev in _ERROR_PATTERNS:
            if cat == category:
                severity = sev
                break
        anomalies.append({
            "pattern": category,
            "evidence_count": count,
            "severity": severity,
            "baseline_comparison": f"检测到 {count} 条相关日志（基线预期 < 3 条/30min）" if count > 2 else "在正常范围内",
        })

    # Cross-source correlation heuristics
    correlations = _detect_correlations(logs, key_events)

    # Summary
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    top_events = sorted(key_events, key=lambda e: severity_order.get(e.get("significance", "low"), 99))[:5]
    summary_parts = [f"{e.get('category', '')}: {e.get('message', '')[:60]}" for e in top_events]

    return {
        "summary": f"过去30分钟内检测到 {total_errors} 条异常日志。关键事件: {'; '.join(summary_parts[:3])}。" if summary_parts else "未检测到明显异常日志模式。",
        "key_events": key_events[:10],
        "anomalies": anomalies,
        "correlations": correlations,
        "error_categories": [
            {"category": cat, "count": cnt, "percentage": round(cnt / max(total_errors, 1) * 100, 1)}
            for cat, cnt in sorted(error_categories.items(), key=lambda x: -x[1])
        ],
        "total_errors": total_errors,
        "method": "rule_based",
    }


def _detect_correlations(logs: List[Dict[str, Any]], key_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Heuristic cross-source correlation detection."""
    correlations: List[Dict[str, Any]] = []
    sources = set(e.get("source", "") for e in key_events)

    # DB + App timeout correlation
    has_db = any("db/" in s or "postgres" in s for s in sources)
    has_app = any("app/" in s for s in sources)
    if has_db and has_app:
        correlations.append({
            "sources": [s for s in sources if "db/" in s or "app/" in s],
            "pattern_description": "应用层连接超时与数据库层错误同时出现，疑似数据库连接池耗尽或慢查询引发的级联故障。",
            "confidence": 0.82,
        })

    # Host resource + App error correlation
    has_host = any("host/" in s for s in sources)
    if has_host and has_app:
        correlations.append({
            "sources": [s for s in sources if "host/" in s or "app/" in s],
            "pattern_description": "主机资源异常与应用错误并发，可能是资源耗尽（CPU/内存/磁盘/文件描述符）直接导致应用不可用。",
            "confidence": 0.75,
        })

    # K8s + App correlation
    has_k8s = any("k8s/" in s for s in sources)
    if has_k8s and has_app:
        correlations.append({
            "sources": [s for s in sources if "k8s/" in s or "app/" in s],
            "pattern_description": "K8s 层面的事件（OOMKilled/健康检查失败）与应用错误高度相关，建议检查 Pod 资源限制和存活探针配置。",
            "confidence": 0.78,
        })

    return correlations


# ---------------------------------------------------------------------------
# LogAnalyzer
# ---------------------------------------------------------------------------

class LogAnalyzer:
    """Analyzes log data and produces structured summaries for the reasoner."""

    @staticmethod
    async def analyze(
        incident: Dict[str, Any],
        logs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Main entry point — analyze logs and return structured result.

        If no logs provided, generates simulated logs from the incident pattern.
        """
        if logs is None:
            logs = generate_simulated_logs(incident)

        if not logs:
            return {
                "summary": "无可用日志数据。",
                "key_events": [],
                "anomalies": [],
                "correlations": [],
                "error_categories": [],
                "total_errors": 0,
                "method": "empty",
            }

        client = LLMClient()

        if client.provider in ("openai", "anthropic", "ollama"):
            try:
                return await LogAnalyzer._llm_analyze(incident, logs, client)
            except Exception:
                pass  # fall through to rule-based

        return _rule_based_analyze(logs, incident)

    @staticmethod
    async def _llm_analyze(
        incident: Dict[str, Any],
        logs: List[Dict[str, Any]],
        client: LLMClient,
    ) -> Dict[str, Any]:
        """LLM-powered log analysis."""
        services = [s.get("name", s.get("id", "")) for s in incident.get("kg_context", {}).get("services", [])]
        alerts = [a.get("name", a.get("id", "")) for a in incident.get("kg_context", {}).get("alerts", [])]
        changes = [c.get("name", c.get("id", "")) for c in incident.get("kg_context", {}).get("changes", [])]

        user_prompt = LOG_ANALYSIS_USER.format(
            summary=incident.get("summary", ""),
            services=", ".join(services) if services else "未知",
            alerts=", ".join(alerts) if alerts else "无",
            changes=", ".join(changes) if changes else "无",
            logs_json=json.dumps(logs, ensure_ascii=False, indent=2),
        )

        response: LLMResponse = await client.infer(
            prompt=user_prompt,
            system=LOG_ANALYSIS_SYSTEM,
            json_mode=(client.provider == "openai"),
            temperature=0.0,
            max_tokens=2048,
        )

        # Parse JSON from response
        text = response.text.strip()
        # Remove code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            text = "\n".join(lines).strip()

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            # Try bracket extraction
            start = text.find("{")
            if start >= 0:
                brace_level = 0
                for i, ch in enumerate(text[start:], start=start):
                    if ch == "{":
                        brace_level += 1
                    elif ch == "}":
                        brace_level -= 1
                        if brace_level == 0:
                            result = json.loads(text[start : i + 1])
                            break
                else:
                    raise ValueError("JSON extraction failed")
            else:
                raise ValueError("No JSON found in LLM response")

        result["method"] = "llm"
        result["model"] = response.model
        result["latency_ms"] = response.latency_ms
        return result

    @staticmethod
    def inject_into_kg_context(
        kg_context: Dict[str, Any],
        log_analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Inject log analysis results into the KG context for the reasoner."""
        kg_context["log_analysis"] = log_analysis
        return kg_context
