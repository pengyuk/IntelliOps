"""
Discussion Sync Agent — bridges the gap between human discussion threads and Copilot reasoning.

This agent monitors the incident discussion board and:
1. Extracts key evidence/decisions from developer/maintainer messages
2. Automatically syncs discussion evidence into Copilot's conversation context
3. Triggers root cause confidence updates when critical evidence appears
4. Automatically records discussion decisions into the incident timeline

The agent acts as a "listener" — when new discussion messages arrive, it evaluates
whether they contain actionable evidence and, if so, feeds them into the Copilot
diagnosis loop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .db import get_db

DB = get_db()


# ---------------------------------------------------------------------------
# Evidence extraction patterns
# ---------------------------------------------------------------------------

# Patterns that indicate a discussion message contains evidence worth
# feeding to the Copilot for root cause analysis updates.
EVIDENCE_PATTERNS = [
    # 变更相关
    (re.compile(r'(改|调整|修改|更新|变更|部署|上线|发布|回滚)了.{0,20}(配置|参数|代码|版本|连接池|超时|阈值|开关)'), 'change', 0.9),
    # 确认根因
    (re.compile(r'(确实|确认|就是|的确是|根因|原因)是.{0,30}(连接池|数据库|网络|配置|内存|磁盘|CPU|依赖|超时|慢查询|OOM)'), 'confirmation', 0.95),
    # 操作执行
    (re.compile(r'(已|已经|刚|刚刚)(重启|回滚|扩容|降级|切换|切流|停服|kill|stop)'), 'action_taken', 0.85),
    # 系统状态
    (re.compile(r'(恢复了|正常了|降了|消失了|好了|OK了|恢复了?正常)'), 'recovery', 0.8),
    (re.compile(r'(还在|持续|继续|仍然|依然)(报错|告警|异常|失败|超时|延迟)'), 'ongoing', 0.8),
    # 关键发现
    (re.compile(r'(发现|看到|查到|注意到|观察到).{0,20}(日志|错误|异常|堆栈|指标|告警|瓶颈)'), 'discovery', 0.82),
    # 交接/升级
    (re.compile(r'(交接|转交|升级|escalate|求助|帮忙看看)'), 'handoff', 0.7),
]


@dataclass
class DiscussionEvidence:
    """Extracted evidence from a discussion message."""
    message_id: str
    incident_id: str
    author: str
    role: str          # operator / developer / approver
    message_type: str  # maintenance / development / decision / evidence
    original_text: str
    evidence_type: str  # change / confirmation / action_taken / recovery / discovery / handoff / generic
    confidence: float
    extracted_summary: str
    should_update_root_cause: bool = False
    should_add_timeline: bool = False


@dataclass
class SyncResult:
    """Result of syncing discussion to Copilot context."""
    evidence_found: bool
    evidence_list: List[DiscussionEvidence] = field(default_factory=list)
    root_cause_updated: bool = False
    timeline_events_added: int = 0
    summary: str = ""


# ---------------------------------------------------------------------------
# DiscussionSyncAgent
# ---------------------------------------------------------------------------

class DiscussionSyncAgent:
    """Monitors discussions and syncs evidence to Copilot diagnosis context."""

    @staticmethod
    async def extract_evidence(
        incident_id: str,
        discussion_messages: List[Dict[str, Any]],
    ) -> List[DiscussionEvidence]:
        """Scan discussion messages and extract actionable evidence."""
        evidence_list: List[DiscussionEvidence] = []

        for msg in discussion_messages:
            # Skip copilot's own messages and system messages
            if msg.get('role') in ('copilot', 'system') or msg.get('author') == 'copilot':
                continue

            text = msg.get('message', '')
            msg_type = msg.get('message_type', 'discussion')
            author = msg.get('author', 'unknown')
            role = msg.get('role', 'unknown')

            for pattern, ev_type, confidence in EVIDENCE_PATTERNS:
                m = pattern.search(text)
                if m:
                    evidence = DiscussionEvidence(
                        message_id=msg.get('comment_id', ''),
                        incident_id=incident_id,
                        author=author,
                        role=role,
                        message_type=msg_type,
                        original_text=text[:200],
                        evidence_type=ev_type,
                        confidence=confidence,
                        extracted_summary=m.group(0) if m.lastindex else text[:100],
                    )

                    # Decision-type messages should always update root cause
                    if msg_type == 'decision':
                        evidence.should_update_root_cause = True
                        evidence.should_add_timeline = True

                    # Confirmation-type evidence is high value
                    if ev_type in ('confirmation', 'change'):
                        evidence.should_update_root_cause = True
                        evidence.should_add_timeline = True

                    # Actions taken should be recorded
                    if ev_type == 'action_taken':
                        evidence.should_add_timeline = True

                    evidence_list.append(evidence)
                    break  # first matching pattern wins

        return evidence_list

    @staticmethod
    def build_discussion_context_for_copilot(
        evidence_list: List[DiscussionEvidence],
        recent_messages: List[Dict[str, Any]],
    ) -> str:
        """Build a discussion context block for injection into Copilot's user prompt.
        
        This gives the Copilot visibility into what developers and other operators
        have been discussing about this incident.
        """
        if not recent_messages:
            return ""

        lines = ["## 💬 最近协同讨论（开发/运维侧）"]
        lines.append("以下是与开发人员和其他运维人员的讨论记录，请参考其中的关键信息更新你的分析。\n")

        for msg in recent_messages[-8:]:  # last 8 messages
            author = msg.get('author', 'unknown')
            role = msg.get('role', 'unknown')
            msg_type = msg.get('message_type', 'discussion')
            text = msg.get('message', '')[:200]

            # Skip copilot's own messages
            if author == 'copilot':
                continue

            # Role badge
            role_badge = {
                'operator': '🛠️ 运维',
                'developer': '💻 开发',
                'approver': '✅ 审批',
            }.get(role, '👤 其他')

            # Type indicator
            type_marker = ''
            if msg_type == 'decision':
                type_marker = '🔑 [关键决策] '
            elif msg_type == 'evidence':
                type_marker = '🔍 [证据] '
            elif msg_type == 'conclusion':
                type_marker = '📋 [结论] '
            elif msg_type == 'handoff':
                type_marker = '🔄 [交接] '

            lines.append(f"[{role_badge}] {type_marker}{text}")

        # Highlight extracted evidence
        if evidence_list:
            lines.append("\n### 从讨论中提取的关键证据")
            for ev in evidence_list:
                icon = {
                    'change': '🔧', 'confirmation': '✅', 'action_taken': '⚡',
                    'recovery': '🟢', 'ongoing': '🔴', 'discovery': '🔍',
                    'handoff': '🔄',
                }.get(ev.evidence_type, '📌')
                lines.append(f"- {icon} [{ev.role}] {ev.extracted_summary}（可信度: {ev.confidence:.0%}）")

        return '\n'.join(lines)

    @staticmethod
    async def sync_to_timeline(
        incident_id: str,
        evidence: DiscussionEvidence,
        add_timeline_fn,
    ) -> Optional[Dict[str, Any]]:
        """Record a discussion-derived event to the incident timeline."""
        if not add_timeline_fn:
            return None

        event_type_map = {
            'change': 'evidence_change',
            'confirmation': 'root_cause_confirmed',
            'action_taken': 'action_taken',
            'recovery': 'recovery_indication',
            'discovery': 'evidence_found',
            'handoff': 'handoff',
        }

        event_type = event_type_map.get(evidence.evidence_type, 'discussion_insight')
        summary = f"[协同讨论] {evidence.role}: {evidence.extracted_summary[:100]}"

        return await add_timeline_fn(
            incident_id, event_type, summary,
            evidence.author, evidence.role,
            f'来源: 讨论消息 {evidence.message_id}\n原文: {evidence.original_text}',
        )


# ---------------------------------------------------------------------------
# Convenience function for app.py integration
# ---------------------------------------------------------------------------

async def sync_discussion_to_copilot(
    incident_id: str,
    diagnosis: Dict[str, Any],
    add_timeline_fn=None,
) -> SyncResult:
    """Main entry point: sync recent discussion messages to Copilot context.
    
    Called from app.py /copilot/chat before each Copilot inference.
    """
    agent = DiscussionSyncAgent()
    result = SyncResult()

    try:
        # Fetch recent discussion messages
        recent = await DB.list_discussion(incident_id)
        if not recent:
            result.summary = "无讨论消息"
            return result

        # Extract evidence
        evidence_list = await agent.extract_evidence(incident_id, recent)
        result.evidence_found = len(evidence_list) > 0
        result.evidence_list = evidence_list

        # Build context and inject into diagnosis
        context_block = agent.build_discussion_context_for_copilot(evidence_list, recent)
        if context_block:
            # Store for copilot.py to use
            diagnosis['_discussion_context'] = context_block
            diagnosis['_discussion_evidence'] = [
                {
                    'type': ev.evidence_type,
                    'summary': ev.extracted_summary,
                    'confidence': ev.confidence,
                    'author_role': ev.role,
                }
                for ev in evidence_list
            ]

        # Sync high-value evidence to timeline
        for ev in evidence_list:
            if ev.should_add_timeline and add_timeline_fn:
                await agent.sync_to_timeline(incident_id, ev, add_timeline_fn)
                result.timeline_events_added += 1

        result.summary = (
            f"从 {len(recent)} 条讨论中提取 {len(evidence_list)} 条证据"
            f"，其中 {result.timeline_events_added} 条已写入时间线"
        )

    except Exception as e:
        result.summary = f"讨论同步失败: {e}"

    return result


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_sync_agent: Optional[DiscussionSyncAgent] = None


def get_sync_agent() -> DiscussionSyncAgent:
    global _sync_agent
    if _sync_agent is None:
        _sync_agent = DiscussionSyncAgent()
    return _sync_agent
