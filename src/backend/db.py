"""
SQLite database layer — replaces in-memory Dict/List stores.

Tables: incidents, timeline_events, discussion_messages, scripts,
        diagnoses, action_logs, action_requests, postmortems, knowledge_assets

Usage:
    from .db import get_db
    db = get_db()
    await db.init()
    incidents = await db.list_incidents()
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiosqlite

DB_PATH = os.environ.get("INTELLIOPS_DB", "data/intelliops.db")


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _json_loads(text: Optional[str]) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            self._conn = await aiosqlite.connect(self.path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    async def init(self) -> None:
        print("[DB] Initializing database...")
        db = await self._get_conn()
        print("[DB]   → Creating tables...")
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                status TEXT DEFAULT 'Investigating',
                summary TEXT DEFAULT '',
                related_alerts TEXT DEFAULT '[]',
                related_changes TEXT DEFAULT '[]',
                affected_services TEXT DEFAULT '[]',
                root_cause TEXT DEFAULT '',
                resolution_steps TEXT DEFAULT '[]',
                scripts_used TEXT DEFAULT '[]',
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS timeline_events (
                event_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                event_type TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                actor TEXT DEFAULT '',
                role TEXT DEFAULT '',
                details TEXT DEFAULT '',
                sequence INTEGER DEFAULT 0,
                timestamp TEXT DEFAULT '',
                FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
            );

            CREATE TABLE IF NOT EXISTS discussion_messages (
                comment_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                author TEXT DEFAULT '',
                role TEXT DEFAULT '',
                message TEXT DEFAULT '',
                message_type TEXT DEFAULT 'discussion',
                mentions TEXT DEFAULT '[]',
                diagnosis_id TEXT DEFAULT '',
                suggested_actions TEXT DEFAULT '[]',
                execution_id TEXT DEFAULT '',
                created_at TEXT DEFAULT '',
                FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
            );

            CREATE TABLE IF NOT EXISTS scripts (
                script_id TEXT PRIMARY KEY,
                name TEXT DEFAULT '',
                language TEXT DEFAULT 'bash',
                code TEXT DEFAULT '',
                category TEXT DEFAULT 'copilot_generated',
                risk_level TEXT DEFAULT 'medium',
                explanation TEXT DEFAULT '',
                approval_required INTEGER DEFAULT 0,
                confidence REAL DEFAULT 0.5,
                incident_id TEXT DEFAULT '',
                diagnosis_id TEXT DEFAULT '',
                knowledge_asset INTEGER DEFAULT 0,
                created_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS diagnoses (
                diagnosis_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                kg_context TEXT DEFAULT '{}',
                log_analysis TEXT DEFAULT '{}',
                candidate_root_causes TEXT DEFAULT '[]',
                reasoning_steps TEXT DEFAULT '[]',
                evidence TEXT DEFAULT '[]',
                evidence_chain TEXT DEFAULT '[]',
                confidence_summary REAL DEFAULT 0.0,
                initial_recommendations TEXT DEFAULT '[]',
                conversation_history TEXT DEFAULT '[]',
                diagnostic_session_started INTEGER DEFAULT 0,
                method TEXT DEFAULT 'rule_based',
                model TEXT DEFAULT '',
                latency_ms REAL DEFAULT 0.0,
                created_at TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
            );

            CREATE TABLE IF NOT EXISTS action_requests (
                request_id TEXT PRIMARY KEY,
                action_id TEXT DEFAULT '',
                incident_id TEXT DEFAULT '',
                reason TEXT DEFAULT '',
                requested_by TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                approver TEXT DEFAULT '',
                comment TEXT DEFAULT '',
                executed_by TEXT DEFAULT '',
                created_at TEXT DEFAULT '',
                approved_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS action_logs (
                exec_id TEXT PRIMARY KEY,
                execution_id TEXT DEFAULT '',
                action_id TEXT DEFAULT '',
                script_name TEXT DEFAULT '',
                incident_id TEXT DEFAULT '',
                diagnosis_id TEXT DEFAULT '',
                status TEXT DEFAULT 'success',
                output TEXT DEFAULT '',
                conclusion TEXT DEFAULT '',
                next_suggestion TEXT DEFAULT '',
                requested_by TEXT DEFAULT '',
                request_id TEXT DEFAULT '',
                dry_run INTEGER DEFAULT 0,
                lifecycle_type TEXT DEFAULT 'once',
                fed_to_copilot INTEGER DEFAULT 0,
                params TEXT DEFAULT '{}',
                created_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS postmortems (
                postmortem_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                status TEXT DEFAULT 'draft',
                timeline TEXT DEFAULT '[]',
                root_cause_conclusion TEXT DEFAULT '{}',
                decisions TEXT DEFAULT '[]',
                tools_used TEXT DEFAULT '[]',
                scripts_used TEXT DEFAULT '[]',
                improvement_suggestions TEXT DEFAULT '[]',
                approved_by TEXT DEFAULT '',
                approved_at TEXT DEFAULT '',
                published_scripts TEXT DEFAULT '[]',
                improvement_tasks_created INTEGER DEFAULT 0,
                created_at TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
            );

            CREATE TABLE IF NOT EXISTS knowledge_assets (
                postmortem_id TEXT PRIMARY KEY,
                knowledge_id TEXT DEFAULT '',
                root_cause_rules TEXT DEFAULT '[]',
                warning_signals TEXT DEFAULT '[]',
                sop_templates TEXT DEFAULT '[]',
                script_recommendations TEXT DEFAULT '[]',
                key_learnings TEXT DEFAULT '[]',
                related_tags TEXT DEFAULT '[]',
                method TEXT DEFAULT 'rule_based',
                model TEXT DEFAULT '',
                latency_ms REAL DEFAULT 0.0,
                distilled_at TEXT DEFAULT '',
                FOREIGN KEY (postmortem_id) REFERENCES postmortems(postmortem_id)
            );

            CREATE INDEX IF NOT EXISTS idx_timeline_incident ON timeline_events(incident_id);
            CREATE INDEX IF NOT EXISTS idx_discussion_incident ON discussion_messages(incident_id);
            CREATE INDEX IF NOT EXISTS idx_diagnoses_incident ON diagnoses(incident_id);
            CREATE INDEX IF NOT EXISTS idx_action_logs_incident ON action_logs(incident_id);
            CREATE INDEX IF NOT EXISTS idx_scripts_incident ON scripts(incident_id);
            CREATE INDEX IF NOT EXISTS idx_postmortems_incident ON postmortems(incident_id);
        """)
        await db.commit()
        print("[DB]   ✓ Tables created")

    async def seed_from_data_service(self, data_service: Any) -> int:
        """Import real alarm records as incidents. Returns count of imported incidents."""
        db = await self._get_conn()
        row = await db.execute("SELECT COUNT(*) FROM incidents")
        count = (await row.fetchone())[0]
        if count > 0:
            print("[DB]   Incidents already seeded, skipping")
            return 0  # already seeded

        if not data_service or not data_service.alarm_records:
            print("[DB]   No alarm records in DataService, fallback to demo seed")
            await self._seed()  # fallback to demo
            return 0

        print(f"[DB]   → Importing from {len(data_service.alarm_records)} alarm records...")
        imported = 0
        now = _now_iso()
        for alarm in data_service.alarm_records[:20]:  # top 20 alarms
            if imported >= 10:
                break
            alarm_id = alarm.get("alarm_id", "")
            summary = alarm.get("alarm_name", "") or alarm.get("alarm_description", "")[:40]
            if not summary:
                continue

            # Determine status from severity
            severity = int(alarm.get("severity", 1))
            status = "Investigating" if severity >= 3 else "Resolved"

            # Map related systems to affected_services
            related = alarm.get("related_systems", [])
            if not related:
                system_name = alarm.get("system", "")
                if system_name:
                    related = [system_name]

            await db.execute(
                "INSERT INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    alarm_id,
                    status,
                    summary[:60],
                    _json_dumps([alarm_id]),
                    _json_dumps([]),
                    _json_dumps(related),
                    "",
                    "[]",
                    "[]",
                    alarm.get("alert_time", now),
                    now,
                ),
            )
            await db.execute(
                "INSERT INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    f"evt-{alarm_id}",
                    alarm_id,
                    "alert",
                    summary[:80],
                    "system",
                    "system",
                    alarm.get("alarm_description", "")[:200],
                    imported + 1,
                    alarm.get("alert_time", now),
                ),
            )
            imported += 1

        await db.commit()
        print(f"[DB]   ✓ Imported {imported} incidents from alarm records")
        return imported

    async def _seed(self) -> None:
        db = await self._get_conn()
        print("[DB]   → Ensuring 2 showcase incidents...")

        # =================================================================
        # Case 1: IGTBNET-BUS 微服务成功率下降 (未结案, 用于演示LLM诊断)
        # 来源: data/告警信息/4月26日告警.xls
        # =================================================================
        await db.execute(
            "INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "inc-igtb-001",
                "Investigating",
                "IGTBNET-BUS/igtb-srv-cds 业务成功率-微服务持续低于80%阈值",
                '["al-igtb-001"]',
                "[]",
                '["svc-igtbnet","svc-igtbcds","svc-mcis"]',
                "",
                "[]",
                "[]",
                "2026-04-26T22:18:40Z",
                "2026-04-26T22:18:40Z",
            ),
        )
        # Timeline for Case 1
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-igtb-1", "inc-igtb-001", "alert", "IGTBNET-BUS 微服务成功率降至69.77%，触发三级告警", "system", "system",
             "BPPM监控检测到 igtb-srv-cds 在5min内[业务成功率-微服务]超出阈值[<80.08%]4次，告警峰值69.77%，策略ID：46816。涉及北京黑山扈信创3主机。", 1, "2026-04-26T22:02:26Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-igtb-2", "inc-igtb-001", "investigation", "运维人员接手告警，开始排查", "ops-manager", "approver",
             "胡海峰(应用维护一部)接手告警。初步检查：告警集中在22:15-22:17时间窗口，5分钟内触发4次。当前微服务成功率仅69.77%，严重偏离正常基线(>95%)。", 2, "2026-04-26T22:05:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-igtb-3", "inc-igtb-001", "escalation", "关联下游MCIS系统确认影响范围", "ops-manager", "approver",
             "排查发现IGTBNET-BUS与下游MCIS(多渠道集成)系统存在依赖关系。需要确认IGTBNET-BUS微服务异常是否已影响MCIS到分行CSP的链路。", 3, "2026-04-26T22:10:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-igtb-4", "inc-igtb-001", "note", "告警持续触发 —— 同日已有多次同类告警", "system", "system",
             "4月26日全天IGTBNET-BUS已触发多次同类告警：18:36(峰值74.15%)、20:33(峰值72.28%)、21:33(峰值59.8%)、22:18(峰值69.77%)。疑似存在周期性性能退化。", 4, "2026-04-26T22:30:00Z"),
        )
        # Discussion for Case 1
        await db.execute(
            "INSERT OR REPLACE INTO discussion_messages VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("cmt-igtb-1", "inc-igtb-001", "ops-manager", "approver",
             "IGTBNET-BUS 今天已经是第4次触发同类告警了。看历史趋势，18点、20点、21点、22点都有，像是周期性问题。需要确认是不是有定时任务或批量处理在这个时间段运行？",
             "discussion", "[]", "", "[]", "", "2026-04-26T22:35:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO discussion_messages VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("cmt-igtb-2", "inc-igtb-001", "dev-user", "developer",
             "igtb-srv-cds 最近没有变更。建议先查一下黑山扈信创3主机的资源使用情况——CPU、内存、连接数。另外看一下下游MCIS的调用延迟是否同步上升，如果是的话可能问题在主机层面而非应用层。",
             "discussion", "[]", "", "[]", "", "2026-04-26T22:40:00Z"),
        )

        # =================================================================
        # Case 2: BOCS-DNF 数据下刷延迟 (已结案, 用于演示完整故障复盘)
        # 来源: data/故障复盘报告/ (3份docx报告)
        # =================================================================
        await db.execute(
            "INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "inc-bocs-001",
                "Resolved",
                "BOCS-D向BOCS-DNF MQ数据同步堆积，QREP通道延迟，威胁DNF交易回切",
                '["al-bocs-001"]',
                '["chg-dnf-001"]',
                '["svc-bocsd","svc-bocsdnf","mq-bocs","mq-dnf"]',
                "MQ QREP通道消息格式兼容性问题导致堆积，清理异常消息后恢复",
                '["检查MQ通道状态","清理QREP异常堆积消息","验证DNF数据同步恢复","确认DNF交易回切窗口安全"]',
                "[]",
                "2026-03-31T04:29:00Z",
                "2026-03-31T06:30:00Z",
            ),
        )
        # Timeline for Case 2 — based on real postmortem reports
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-bocs-1", "inc-bocs-001", "alert", "系统平台一部收到主机核心QREP堆积告警", "system", "system",
             "4:29-4:37，系统平台一部收到MQ异常告警，发现BOCS-D到BOCS-DNF的QREP通道存在消息堆积。黑山扈主机MIPS111,210，内存1280GB。", 1, "2026-03-31T04:29:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-bocs-2", "inc-bocs-001", "escalation", "考虑到DNF交易回切风险，启动升级上报", "ops-manager", "approver",
             "5:44，应用维护一部、系统平台一部将异常情况和准备的处置应急升级报送。考虑到DNF MQ持续堆积造成的数据同步延迟可能影响原定7:00的DNF交易回切。", 2, "2026-03-31T05:44:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-bocs-3", "inc-bocs-001", "investigation", "开发一部主管到达现场，联合排查QREP堆积根因", "dev-user", "developer",
             "5:58-6:17，开发一部主管到达ECC。经联合排查，确认QREP通道存在消息格式兼容性问题，导致部分消息无法被DNF侧正常消费，形成堆积。", 3, "2026-03-31T05:58:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-bocs-4", "inc-bocs-001", "action", "执行QREP异常消息清理操作", "ops-manager", "approver",
             "经当值经理审批，执行QREP通道异常消息清理。操作范围：清理无法消费的堆积消息，保留正常排队消息。清理后通道逐步恢复。", 4, "2026-03-31T06:17:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-bocs-5", "inc-bocs-001", "resolution", "数据同步恢复，DNF交易回切窗口安全", "system", "system",
             "6:30确认BOCS-D到BOCS-DNF数据同步恢复正常，QREP通道延迟降至正常水平（<1s）。7:00 DNF交易回切按原计划执行。", 5, "2026-03-31T06:30:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-bocs-6", "inc-bocs-001", "postmortem", "故障复盘：沉淀根因与改进措施", "ops-manager", "approver",
             "复盘结论：根因为QREP消息格式兼容性问题。改进措施：(1)补充MQ通道消息格式兼容性监控；(2)建立DNF回切前的QREP预检机制；(3)将清理操作SOP沉淀为自动化脚本。", 6, "2026-04-01T10:00:00Z"),
        )
        # Discussion for Case 2
        await db.execute(
            "INSERT OR REPLACE INTO discussion_messages VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("cmt-bocs-1", "inc-bocs-001", "ops-manager", "approver",
             "QREP堆积速度在加快，如果6:30前清不完，7:00的DNF交易回切就必须推迟。先评估一下清理预计耗时。",
             "discussion", "[]", "", "[]", "", "2026-03-31T06:00:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO discussion_messages VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("cmt-bocs-2", "inc-bocs-001", "dev-user", "developer",
             "确认了，是QREP通道的消息格式兼容性问题。不是MQ本身的问题，是BOCS-D侧推送的消息中有部分字段格式DNF侧解析不了。建议先清理异常消息，然后我们补充格式校验逻辑。",
             "discussion", "[]", "", "[]", "", "2026-03-31T06:10:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO discussion_messages VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("cmt-bocs-3", "inc-bocs-001", "ops-manager", "approver",
             "清理完成，QREP恢复正常。这次经验需要沉淀：下次DNF回切前增加QREP预检步骤，避免类似问题影响切换窗口。",
             "discussion", "[]", "", "[]", "", "2026-03-31T06:35:00Z"),
        )

        await db.commit()
        print("[DB]   ✓ 2 showcase incidents ensured (inc-igtb-001, inc-bocs-001)")

    # ------------------------------------------------------------------
    # Incidents
    # ------------------------------------------------------------------

    async def list_incidents(self) -> List[Dict[str, Any]]:
        db = await self._get_conn()
        rows = await db.execute("SELECT * FROM incidents ORDER BY created_at DESC")
        return [_row_to_dict(r) for r in await rows.fetchall()]

    async def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        db = await self._get_conn()
        row = await db.execute("SELECT * FROM incidents WHERE incident_id=?", (incident_id,))
        r = await row.fetchone()
        return _row_to_dict(r) if r else None

    async def upsert_incident(self, incident: Dict[str, Any]) -> None:
        db = await self._get_conn()
        now = _now_iso()
        incident.setdefault("created_at", now)
        incident["updated_at"] = now
        await db.execute(
            """INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                incident.get("incident_id"),
                incident.get("status", "Investigating"),
                incident.get("summary", ""),
                _json_dumps(incident.get("related_alerts", [])),
                _json_dumps(incident.get("related_changes", [])),
                _json_dumps(incident.get("affected_services", [])),
                incident.get("root_cause", ""),
                _json_dumps(incident.get("resolution_steps", [])),
                _json_dumps(incident.get("scripts_used", [])),
                incident.get("created_at", now),
                now,
            ),
        )
        await db.commit()

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    async def list_timeline(self, incident_id: str) -> List[Dict[str, Any]]:
        db = await self._get_conn()
        rows = await db.execute(
            "SELECT * FROM timeline_events WHERE incident_id=? ORDER BY timestamp DESC, sequence DESC",
            (incident_id,),
        )
        return [_row_to_dict(r) for r in await rows.fetchall()]

    async def add_timeline_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        db = await self._get_conn()
        await db.execute(
            """INSERT INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                event.get("event_id"),
                event.get("incident_id"),
                event.get("event_type", ""),
                event.get("summary", ""),
                event.get("actor", ""),
                event.get("role", ""),
                event.get("details", ""),
                event.get("sequence", 0),
                event.get("timestamp", _now_iso()),
            ),
        )
        await db.commit()
        return event

    # ------------------------------------------------------------------
    # Discussion
    # ------------------------------------------------------------------

    async def list_discussion(self, incident_id: str, message_type: str = "") -> List[Dict[str, Any]]:
        db = await self._get_conn()
        if message_type:
            rows = await db.execute(
                "SELECT * FROM discussion_messages WHERE incident_id=? AND message_type=? ORDER BY created_at DESC",
                (incident_id, message_type),
            )
        else:
            rows = await db.execute(
                "SELECT * FROM discussion_messages WHERE incident_id=? ORDER BY created_at DESC",
                (incident_id,),
            )
        return [_row_to_dict(r) for r in await rows.fetchall()]

    async def add_discussion(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        db = await self._get_conn()
        await db.execute(
            """INSERT INTO discussion_messages VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                msg.get("comment_id"),
                msg.get("incident_id"),
                msg.get("author", ""),
                msg.get("role", ""),
                msg.get("message", ""),
                msg.get("message_type", "discussion"),
                _json_dumps(msg.get("mentions", [])),
                msg.get("diagnosis_id", ""),
                _json_dumps(msg.get("suggested_actions", [])),
                msg.get("execution_id", ""),
                msg.get("created_at", _now_iso()),
            ),
        )
        await db.commit()
        return msg

    # ------------------------------------------------------------------
    # Scripts
    # ------------------------------------------------------------------

    async def get_script(self, script_id: str) -> Optional[Dict[str, Any]]:
        db = await self._get_conn()
        row = await db.execute("SELECT * FROM scripts WHERE script_id=?", (script_id,))
        r = await row.fetchone()
        return _row_to_dict(r) if r else None

    async def list_scripts(self, incident_id: str = "") -> List[Dict[str, Any]]:
        db = await self._get_conn()
        if incident_id:
            rows = await db.execute("SELECT * FROM scripts WHERE incident_id=?", (incident_id,))
        else:
            rows = await db.execute("SELECT * FROM scripts")
        return [_row_to_dict(r) for r in await rows.fetchall()]

    async def upsert_script(self, script: Dict[str, Any]) -> Dict[str, Any]:
        db = await self._get_conn()
        await db.execute(
            """INSERT OR REPLACE INTO scripts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                script.get("script_id"),
                script.get("name", ""),
                script.get("language", "bash"),
                script.get("code", ""),
                script.get("category", "copilot_generated"),
                script.get("risk_level", "medium"),
                script.get("explanation", ""),
                int(script.get("approval_required", False)),
                script.get("confidence", 0.5),
                script.get("incident_id", ""),
                script.get("diagnosis_id", ""),
                int(script.get("knowledge_asset", False)),
                script.get("created_at", _now_iso()),
            ),
        )
        await db.commit()
        return script

    # ------------------------------------------------------------------
    # Diagnoses
    # ------------------------------------------------------------------

    async def get_diagnosis(self, diagnosis_id: str) -> Optional[Dict[str, Any]]:
        db = await self._get_conn()
        row = await db.execute("SELECT * FROM diagnoses WHERE diagnosis_id=?", (diagnosis_id,))
        r = await row.fetchone()
        return _row_to_dict(r) if r else None

    async def list_diagnoses(self, incident_id: str = "") -> List[Dict[str, Any]]:
        db = await self._get_conn()
        if incident_id:
            rows = await db.execute("SELECT * FROM diagnoses WHERE incident_id=? ORDER BY created_at DESC", (incident_id,))
        else:
            rows = await db.execute("SELECT * FROM diagnoses ORDER BY created_at DESC")
        return [_row_to_dict(r) for r in await rows.fetchall()]

    async def upsert_diagnosis(self, diagnosis: Dict[str, Any]) -> Dict[str, Any]:
        db = await self._get_conn()
        await db.execute(
            """INSERT OR REPLACE INTO diagnoses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                diagnosis.get("diagnosis_id"),
                diagnosis.get("incident_id", ""),
                _json_dumps(diagnosis.get("kg_context", {})),
                _json_dumps(diagnosis.get("log_analysis", {})),
                _json_dumps(diagnosis.get("candidate_root_causes", [])),
                _json_dumps(diagnosis.get("reasoning_steps", [])),
                _json_dumps(diagnosis.get("evidence", [])),
                _json_dumps(diagnosis.get("evidence_chain", [])),
                diagnosis.get("confidence_summary", 0.0),
                _json_dumps(diagnosis.get("initial_recommendations", [])),
                _json_dumps(diagnosis.get("conversation_history", [])),
                int(diagnosis.get("diagnostic_session_started", False)),
                diagnosis.get("method", "rule_based"),
                diagnosis.get("model", ""),
                diagnosis.get("latency_ms", 0.0),
                diagnosis.get("created_at", _now_iso()),
                diagnosis.get("created_by", ""),
            ),
        )
        await db.commit()
        return diagnosis

    # ------------------------------------------------------------------
    # Action requests & logs
    # ------------------------------------------------------------------

    async def list_action_requests(self) -> List[Dict[str, Any]]:
        db = await self._get_conn()
        rows = await db.execute("SELECT * FROM action_requests ORDER BY created_at DESC")
        return [_row_to_dict(r) for r in await rows.fetchall()]

    async def get_action_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        db = await self._get_conn()
        row = await db.execute("SELECT * FROM action_requests WHERE request_id=?", (request_id,))
        r = await row.fetchone()
        return _row_to_dict(r) if r else None

    async def upsert_action_request(self, req: Dict[str, Any]) -> Dict[str, Any]:
        db = await self._get_conn()
        await db.execute(
            """INSERT OR REPLACE INTO action_requests VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                req.get("request_id"),
                req.get("action_id", ""),
                req.get("incident_id", ""),
                req.get("reason", ""),
                req.get("requested_by", ""),
                req.get("status", "pending"),
                req.get("approver", ""),
                req.get("comment", ""),
                req.get("executed_by", ""),
                req.get("created_at", _now_iso()),
                req.get("approved_at", ""),
            ),
        )
        await db.commit()
        return req

    async def list_action_logs(self, incident_id: str = "") -> List[Dict[str, Any]]:
        db = await self._get_conn()
        if incident_id:
            rows = await db.execute("SELECT * FROM action_logs WHERE incident_id=? ORDER BY created_at DESC", (incident_id,))
        else:
            rows = await db.execute("SELECT * FROM action_logs ORDER BY created_at DESC")
        return [_row_to_dict(r) for r in await rows.fetchall()]

    async def add_action_log(self, log: Dict[str, Any]) -> Dict[str, Any]:
        db = await self._get_conn()
        await db.execute(
            """INSERT INTO action_logs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                log.get("exec_id"),
                log.get("execution_id", log.get("exec_id", "")),
                log.get("action_id", ""),
                log.get("script_name", ""),
                log.get("incident_id", ""),
                log.get("diagnosis_id", ""),
                log.get("status", "success"),
                log.get("output", ""),
                log.get("conclusion", ""),
                log.get("next_suggestion", ""),
                log.get("requested_by", ""),
                log.get("request_id", ""),
                int(log.get("dry_run", False)),
                log.get("lifecycle_type", "once"),
                int(log.get("fed_to_copilot", False)),
                _json_dumps(log.get("params", {})),
                log.get("created_at", _now_iso()),
            ),
        )
        await db.commit()
        return log

    # ------------------------------------------------------------------
    # Postmortems
    # ------------------------------------------------------------------

    async def get_postmortem(self, postmortem_id: str) -> Optional[Dict[str, Any]]:
        db = await self._get_conn()
        row = await db.execute("SELECT * FROM postmortems WHERE postmortem_id=?", (postmortem_id,))
        r = await row.fetchone()
        return _row_to_dict(r) if r else None

    async def upsert_postmortem(self, report: Dict[str, Any]) -> Dict[str, Any]:
        db = await self._get_conn()
        await db.execute(
            """INSERT OR REPLACE INTO postmortems
               (postmortem_id, incident_id, status, timeline, root_cause_conclusion,
                decisions, tools_used, scripts_used, improvement_suggestions,
                approved_by, approved_at, published_scripts, improvement_tasks_created,
                created_at, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                report.get("postmortem_id"),
                report.get("incident_id", ""),
                report.get("status", "draft"),
                _json_dumps(report.get("timeline", [])),
                _json_dumps(report.get("root_cause_conclusion", {})),
                _json_dumps(report.get("decisions", [])),
                _json_dumps(report.get("tools_used", [])),
                _json_dumps(report.get("scripts_used", [])),
                _json_dumps(report.get("improvement_suggestions", [])),
                report.get("approved_by", ""),
                report.get("approved_at", ""),
                _json_dumps(report.get("published_scripts", [])),
                int(report.get("improvement_tasks_created", False)),
                report.get("created_at", _now_iso()),
                report.get("created_by", ""),
            ),
        )
        await db.commit()
        return report

    # ------------------------------------------------------------------
    # Knowledge assets
    # ------------------------------------------------------------------

    async def get_knowledge(self, postmortem_id: str) -> Optional[Dict[str, Any]]:
        db = await self._get_conn()
        row = await db.execute("SELECT * FROM knowledge_assets WHERE postmortem_id=?", (postmortem_id,))
        r = await row.fetchone()
        return _row_to_dict(r) if r else None

    async def upsert_knowledge(self, knowledge: Dict[str, Any]) -> Dict[str, Any]:
        db = await self._get_conn()
        await db.execute(
            """INSERT OR REPLACE INTO knowledge_assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                knowledge.get("postmortem_id", ""),
                knowledge.get("knowledge_id", ""),
                _json_dumps(knowledge.get("root_cause_rules", [])),
                _json_dumps(knowledge.get("warning_signals", [])),
                _json_dumps(knowledge.get("sop_templates", [])),
                _json_dumps(knowledge.get("script_recommendations", [])),
                _json_dumps(knowledge.get("key_learnings", [])),
                _json_dumps(knowledge.get("related_tags", [])),
                knowledge.get("method", "rule_based"),
                knowledge.get("model", ""),
                knowledge.get("latency_ms", 0.0),
                knowledge.get("distilled_at", ""),
            ),
        )
        await db.commit()
        return knowledge

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    d = dict(row)
    # Deserialize JSON fields
    json_fields = {
        "related_alerts", "related_changes", "affected_services",
        "resolution_steps", "scripts_used", "mentions", "suggested_actions",
        "kg_context", "log_analysis", "candidate_root_causes",
        "reasoning_steps", "evidence", "evidence_chain",
        "initial_recommendations", "conversation_history",
        "timeline", "root_cause_conclusion", "decisions",
        "tools_used", "improvement_suggestions", "published_scripts",
        "root_cause_rules", "warning_signals", "sop_templates",
        "script_recommendations", "key_learnings", "related_tags",
        "params", "server_matches",
    }
    for key in json_fields:
        if key in d and isinstance(d[key], str):
            d[key] = _json_loads(d[key])
    return d


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_db: Optional[Database] = None


def get_db(path: str = DB_PATH) -> Database:
    global _db
    if _db is None:
        _db = Database(path)
    return _db
