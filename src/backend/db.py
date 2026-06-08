"""
SQLite database layer 鈥?replaces in-memory Dict/List stores.

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
        print("[DB]   鈫?Creating tables...")
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
        print("[DB]   鉁?Tables created")

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

        print(f"[DB]   鈫?Importing from {len(data_service.alarm_records)} alarm records...")
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
        print(f"[DB]   鉁?Imported {imported} incidents from alarm records")
        return imported

    async def _seed(self) -> None:
        db = await self._get_conn()
        print("[DB]   鈫?Ensuring 2 showcase incidents...")

        # =================================================================
        # Case 1: IGTBNET-BUS 寰?湇鍔℃垚鍔熺巼涓嬮檷 (鏈?粨妗? 鐢ㄤ簬婕旂ずLLM璇婃柇)
        # 鏉ユ簮: data/鍛婅?淇℃伅/4鏈?6鏃ュ憡璀?xls
        # =================================================================
        await db.execute(
            "INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "inc-igtb-001",
                "Investigating",
                "IGTBNET-BUS/igtb-srv-cds 业务成功率持续低于80%阈值",
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
            ("evt-igtb-1", "inc-igtb-001", "alert", "IGTBNET-BUS 寰?湇鍔℃垚鍔熺巼闄嶈嚦69.77%锛岃Е鍙戜笁绾у憡璀?, "system", "system",
             "BPPM鐩戞帶妫?娴嬪埌 igtb-srv-cds 鍦?min鍐匸涓氬姟鎴愬姛鐜?寰?湇鍔瓒呭嚭闃堝?糩<80.08%]4娆★紝鍛婅?宄板??9.77%锛岀瓥鐣D锛?6816銆傛秹鍙婂寳浜粦灞辨増淇″垱3涓绘満銆?, 1, "2026-04-26T22:02:26Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-igtb-2", "inc-igtb-001", "investigation", "杩愮淮浜哄憳鎺ユ墜鍛婅?锛屽紑濮嬫帓鏌?, "ops-manager", "approver",
             "鑳℃捣宄?搴旂敤缁存姢涓?閮?鎺ユ墜鍛婅?銆傚垵姝ユ鏌ワ細鍛婅?闆嗕腑鍦?2:15-22:17鏃堕棿绐楀彛锛?鍒嗛挓鍐呰Е鍙?娆°?傚綋鍓嶅井鏈嶅姟鎴愬姛鐜囦粎69.77%锛屼弗閲嶅亸绂绘甯稿熀绾?>95%)銆?, 2, "2026-04-26T22:05:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-igtb-3", "inc-igtb-001", "escalation", "鍏宠仈涓嬫父MCIS绯荤粺纭褰卞搷鑼冨洿", "ops-manager", "approver",
             "鎺掓煡鍙戠幇IGTBNET-BUS涓庝笅娓窶CIS(澶氭笭閬撻泦鎴?绯荤粺瀛樺湪渚濊禆鍏崇郴銆傞渶瑕佺‘璁GTBNET-BUS寰?湇鍔″紓甯告槸鍚﹀凡褰卞搷MCIS鍒板垎琛孋SP鐨勯摼璺??, 3, "2026-04-26T22:10:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-igtb-4", "inc-igtb-001", "note", "鍛婅?鎸佺画瑙﹀彂 鈥斺??鍚屾棩宸叉湁澶氭鍚岀被鍛婅?", "system", "system",
             "4鏈?6鏃ュ叏澶㊣GTBNET-BUS宸茶Е鍙戝娆″悓绫诲憡璀︼細18:36(宄板??4.15%)銆?0:33(宄板??2.28%)銆?1:33(宄板??9.8%)銆?2:18(宄板??9.77%)銆傜枒浼煎瓨鍦ㄥ懆鏈熸?ф?ц兘閫?鍖栥??, 4, "2026-04-26T22:30:00Z"),
        )
        # Discussion for Case 1
        await db.execute(
            "INSERT OR REPLACE INTO discussion_messages VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("cmt-igtb-1", "inc-igtb-001", "ops-manager", "approver",
             "IGTBNET-BUS 浠婂ぉ宸茬粡鏄4娆¤Е鍙戝悓绫诲憡璀︿簡銆傜湅鍘嗗彶瓒嬪娍锛?8鐐广??0鐐广??1鐐广??2鐐归兘鏈夛紝鍍忔槸鍛ㄦ湡鎬ч棶棰樸?傞渶瑕佺‘璁ゆ槸涓嶆槸鏈夊畾鏃朵换鍔℃垨鎵归噺澶勭悊鍦ㄨ繖涓椂闂存杩愯锛?,
             "discussion", "[]", "", "[]", "", "2026-04-26T22:35:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO discussion_messages VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("cmt-igtb-2", "inc-igtb-001", "dev-user", "developer",
             "igtb-srv-cds 鏈?杩戞病鏈夊彉鏇淬?傚缓璁厛鏌ヤ竴涓嬮粦灞辨増淇″垱3涓绘満鐨勮祫婧愪娇鐢ㄦ儏鍐碘?斺?擟PU銆佸唴瀛樸?佽繛鎺ユ暟銆傚彟澶栫湅涓?涓嬩笅娓窶CIS鐨勮皟鐢ㄥ欢杩熸槸鍚﹀悓姝ヤ笂鍗囷紝濡傛灉鏄殑璇濆彲鑳介棶棰樺湪涓绘満灞傞潰鑰岄潪搴旂敤灞傘??,
             "discussion", "[]", "", "[]", "", "2026-04-26T22:40:00Z"),
        )

        # =================================================================
        # Case 2: BOCS-DNF 鏁版嵁涓嬪埛寤惰繜 (宸茬粨妗? 鐢ㄤ簬婕旂ず瀹屾暣鏁呴殰澶嶇洏)
        # 鏉ユ簮: data/鏁呴殰澶嶇洏鎶ュ憡/ (3浠絛ocx鎶ュ憡)
        # =================================================================
        await db.execute(
            "INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "inc-bocs-001",
                "Resolved",
                "BOCS-D鍚態OCS-DNF MQ鏁版嵁鍚屾鍫嗙Н锛孮REP閫氶亾寤惰繜锛屽▉鑳丏NF浜ゆ槗鍥炲垏",
                '["al-bocs-001"]',
                '["chg-dnf-001"]',
                '["svc-bocsd","svc-bocsdnf","mq-bocs","mq-dnf"]',
                "MQ QREP閫氶亾娑堟伅鏍煎紡鍏煎鎬ч棶棰樺鑷村爢绉紝娓呯悊寮傚父娑堟伅鍚庢仮澶?,
                '["妫?鏌Q閫氶亾鐘舵??,"娓呯悊QREP寮傚父鍫嗙Н娑堟伅","楠岃瘉DNF鏁版嵁鍚屾鎭㈠","纭DNF浜ゆ槗鍥炲垏绐楀彛瀹夊叏"]',
                "[]",
                "2026-03-31T04:29:00Z",
                "2026-03-31T06:30:00Z",
            ),
        )
        # Timeline for Case 2 鈥?based on real postmortem reports
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-bocs-1", "inc-bocs-001", "alert", "绯荤粺骞冲彴涓?閮ㄦ敹鍒颁富鏈烘牳蹇僎REP鍫嗙Н鍛婅?", "system", "system",
             "4:29-4:37锛岀郴缁熷钩鍙颁竴閮ㄦ敹鍒癕Q寮傚父鍛婅?锛屽彂鐜癇OCS-D鍒癇OCS-DNF鐨凲REP閫氶亾瀛樺湪娑堟伅鍫嗙Н銆傞粦灞辨増涓绘満MIPS111,210锛屽唴瀛?280GB銆?, 1, "2026-03-31T04:29:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-bocs-2", "inc-bocs-001", "escalation", "鑰冭檻鍒癉NF浜ゆ槗鍥炲垏椋庨櫓锛屽惎鍔ㄥ崌绾т笂鎶?, "ops-manager", "approver",
             "5:44锛屽簲鐢ㄧ淮鎶や竴閮ㄣ?佺郴缁熷钩鍙颁竴閮ㄥ皢寮傚父鎯呭喌鍜屽噯澶囩殑澶勭疆搴旀?ュ崌绾ф姤閫併?傝?冭檻鍒癉NF MQ鎸佺画鍫嗙Н閫犳垚鐨勬暟鎹悓姝ュ欢杩熷彲鑳藉奖鍝嶅師瀹?:00鐨凞NF浜ゆ槗鍥炲垏銆?, 2, "2026-03-31T05:44:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-bocs-3", "inc-bocs-001", "investigation", "寮?鍙戜竴閮ㄤ富绠″埌杈剧幇鍦猴紝鑱斿悎鎺掓煡QREP鍫嗙Н鏍瑰洜", "dev-user", "developer",
             "5:58-6:17锛屽紑鍙戜竴閮ㄤ富绠″埌杈綞CC銆傜粡鑱斿悎鎺掓煡锛岀‘璁REP閫氶亾瀛樺湪娑堟伅鏍煎紡鍏煎鎬ч棶棰橈紝瀵艰嚧閮ㄥ垎娑堟伅鏃犳硶琚獶NF渚ф甯告秷璐癸紝褰㈡垚鍫嗙Н銆?, 3, "2026-03-31T05:58:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-bocs-4", "inc-bocs-001", "action", "鎵цQREP寮傚父娑堟伅娓呯悊鎿嶄綔", "ops-manager", "approver",
             "缁忓綋鍊肩粡鐞嗗鎵癸紝鎵цQREP閫氶亾寮傚父娑堟伅娓呯悊銆傛搷浣滆寖鍥达細娓呯悊鏃犳硶娑堣垂鐨勫爢绉秷鎭紝淇濈暀姝ｅ父鎺掗槦娑堟伅銆傛竻鐞嗗悗閫氶亾閫愭鎭㈠銆?, 4, "2026-03-31T06:17:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-bocs-5", "inc-bocs-001", "resolution", "鏁版嵁鍚屾鎭㈠锛孌NF浜ゆ槗鍥炲垏绐楀彛瀹夊叏", "system", "system",
             "6:30纭BOCS-D鍒癇OCS-DNF鏁版嵁鍚屾鎭㈠姝ｅ父锛孮REP閫氶亾寤惰繜闄嶈嚦姝ｅ父姘村钩锛?1s锛夈??:00 DNF浜ゆ槗鍥炲垏鎸夊師璁″垝鎵ц銆?, 5, "2026-03-31T06:30:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            ("evt-bocs-6", "inc-bocs-001", "postmortem", "鏁呴殰澶嶇洏锛氭矇娣?鏍瑰洜涓庢敼杩涙帾鏂?, "ops-manager", "approver",
             "澶嶇洏缁撹锛氭牴鍥犱负QREP娑堟伅鏍煎紡鍏煎鎬ч棶棰樸?傛敼杩涙帾鏂斤細(1)琛ュ厖MQ閫氶亾娑堟伅鏍煎紡鍏煎鎬х洃鎺э紱(2)寤虹珛DNF鍥炲垏鍓嶇殑QREP棰勬鏈哄埗锛?3)灏嗘竻鐞嗘搷浣淪OP娌夋穩涓鸿嚜鍔ㄥ寲鑴氭湰銆?, 6, "2026-04-01T10:00:00Z"),
        )
        # Discussion for Case 2
        await db.execute(
            "INSERT OR REPLACE INTO discussion_messages VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("cmt-bocs-1", "inc-bocs-001", "ops-manager", "approver",
             "QREP鍫嗙Н閫熷害鍦ㄥ姞蹇紝濡傛灉6:30鍓嶆竻涓嶅畬锛?:00鐨凞NF浜ゆ槗鍥炲垏灏卞繀椤绘帹杩熴?傚厛璇勪及涓?涓嬫竻鐞嗛璁¤?楁椂銆?,
             "discussion", "[]", "", "[]", "", "2026-03-31T06:00:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO discussion_messages VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("cmt-bocs-2", "inc-bocs-001", "dev-user", "developer",
             "纭浜嗭紝鏄疩REP閫氶亾鐨勬秷鎭牸寮忓吋瀹规?ч棶棰樸?備笉鏄疢Q鏈韩鐨勯棶棰橈紝鏄疊OCS-D渚ф帹閫佺殑娑堟伅涓湁閮ㄥ垎瀛楁鏍煎紡DNF渚цВ鏋愪笉浜嗐?傚缓璁厛娓呯悊寮傚父娑堟伅锛岀劧鍚庢垜浠ˉ鍏呮牸寮忔牎楠岄?昏緫銆?,
             "discussion", "[]", "", "[]", "", "2026-03-31T06:10:00Z"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO discussion_messages VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("cmt-bocs-3", "inc-bocs-001", "ops-manager", "approver",
             "娓呯悊瀹屾垚锛孮REP鎭㈠姝ｅ父銆傝繖娆＄粡楠岄渶瑕佹矇娣?锛氫笅娆NF鍥炲垏鍓嶅鍔燪REP棰勬姝ラ锛岄伩鍏嶇被浼奸棶棰樺奖鍝嶅垏鎹㈢獥鍙ｃ??,
             "discussion", "[]", "", "[]", "", "2026-03-31T06:35:00Z"),
        )

        await db.commit()
        print("[DB]   鉁?2 showcase incidents ensured (inc-igtb-001, inc-bocs-001)")

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

    async def list_knowledge(self) -> List[Dict[str, Any]]:
        """List all knowledge assets in the database."""
        db = await self._get_conn()
        rows = await db.execute("SELECT * FROM knowledge_assets ORDER BY distilled_at DESC")
        return [_row_to_dict(r) for r in await rows.fetchall()]

    async def delete_knowledge(self, postmortem_id: str) -> None:
        """Delete a knowledge asset by postmortem_id."""
        db = await self._get_conn()
        await db.execute("DELETE FROM knowledge_assets WHERE postmortem_id=?", (postmortem_id,))
        await db.commit()



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

