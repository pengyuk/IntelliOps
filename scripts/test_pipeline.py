"""
Full pipeline test using FastAPI TestClient (no network needed).
Based on BOCS-DNF data sync delay + MCIS branch thirdparty failure cases.

Usage:
    cd d:/大模型/IntelliOps
    python scripts/test_pipeline.py
"""
import sys, os, json

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
sys.path.insert(0, os.path.join(PROJECT, 'src'))

# Clean old DB
db_path = os.path.join(PROJECT, 'data', 'intelliops.db')
if os.path.exists(db_path):
    os.remove(db_path)

from fastapi.testclient import TestClient
from src.backend.app import app, DB

# Explicitly init DB since TestClient may not trigger deprecated @app.on_event("startup")
import asyncio, traceback
async def _ensure_db():
    print("[test] Manually initializing DB...")
    await DB.init()
    from src.backend.app import _get_data_service
    ds = _get_data_service()
    try:
        await DB.seed_from_data_service(ds)
    except Exception as e:
        print(f"[test] seed_from_data_service skipped: {e}")
    await DB._seed()
    print("[test] DB initialization complete.")

try:
    loop = asyncio.get_event_loop()
    if loop.is_running():
        # Event loop already running (e.g., in Jupyter), create task
        import nest_asyncio
        nest_asyncio.apply()
        loop.run_until_complete(_ensure_db())
    else:
        loop.run_until_complete(_ensure_db())
except RuntimeError:
    asyncio.run(_ensure_db())
except Exception as e:
    print(f"[test] DB init error: {e}")
    traceback.print_exc()

client = TestClient(app)
PASS = 0
FAIL = 0

def step(name, method, path, **kw):
    global PASS, FAIL
    try:
        if method == "GET":
            r = client.get(path, params=kw.get("params", {}))
        else:
            r = client.post(path, json=kw.get("json", {}))
        ok = 200 <= r.status_code < 300
        body = r.json() if ok and r.text else {}
        label = "OK" if ok else f"FAIL[{r.status_code}]"
        print(f"  [{label}] {method} {path}")
        if not ok:
            print(f"         {r.text[:300]}")
            FAIL += 1
        else:
            PASS += 1
        return body
    except Exception as e:
        print(f"  [ERR] {method} {path}: {e}")
        FAIL += 1
        return {}

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

print("\n  IntelliOps Full Pipeline Test (TestClient)")
print("  Cases: BOCS-DNF + MCIS\n")

# 0. Health
section("0. Health & Data")
h = step("health", "GET", "/health")
if h:
    print(f"  Status={h.get('status')}, LLM={h.get('llm',{}).get('provider')}")

ds = step("data", "GET", "/data/summary")
if ds:
    for k, v in ds.items():
        if k != 'source_files':
            print(f"  {k}: {v}")

# 1. KG
section("1. Knowledge Graph")
kg = step("kg", "GET", "/kg/nodes")
nodes = kg.get("nodes", [])
types = {}
for n in nodes:
    t = n.get("type","?")
    types[t] = types.get(t,0)+1
print(f"  Nodes: {len(nodes)}")
for t, c in sorted(types.items()):
    print(f"    {t}: {c}")

# ============================================================
# CASE 1: BOCS-DNF  (raw alert → auto-derive everything)
# ============================================================
section("CASE 1: BOCS-DNF (raw alert input → platform derives all)")

# Test the raw alert endpoint directly
raw1 = step("raw-alert", "POST", "/ingest/raw-alert", json={
    "severity": 4,
    "source": "系统平台一部",
    "content": "【SA-BPPM】MQ: MAR 31 04:15:44 BQREPXDEPS0 SEV=WAR QPS1 NamedQueue: QR.XMITQ1.QPS1.TO.QMA CURRENT DEPTH: 2197878 (CurrentDepth >= 2000000)。04:29 MQ Pageset使用率52.96%。04:37 Pageset使用率76.49%触发一级告警。2603批次投产后D+2日首次历史数据清理，单日清理25亿数据（QREP下刷5亿），远超QREP日常吞吐能力（~1亿/小时），导致MQ Pageset空间持续无法释放，数据下刷延迟无法在7:00前追平，影响DNF交易回切。9:56-9:58切换期间主机出现MaxTask，C-DBC/IPPS/RCPS-IBPS交易成功率分别降至98.19%/96.93%/90.5%。"
})

# Show derivation trace
deriv1 = raw1.get("derivation", {})
inc1 = raw1.get("incident", {}).get("incident_id", "")
print(f"  --- Platform Derivation ---")
print(f"  Input: severity=4, source=系统平台一部")
print(f"  Keywords: {deriv1.get('keywords', [])[:8]}")
print(f"  Matched Systems (KG): {[s['id'] for s in deriv1.get('matched_systems', [])]}")
print(f"  Affected Services: {deriv1.get('matched_system_ids', [])}")
print(f"  Related Changes (KG): {deriv1.get('related_changes', [])}")
print(f"  Related Cases Found: {deriv1.get('related_cases_count', 0)}")
print(f"  Summary Method: {deriv1.get('summary_method', '?')}")
print(f"  --- Generated Incident ---")
print(f"  Incident ID: {inc1}")
print(f"  Summary: {raw1.get('incident', {}).get('summary', '')[:80]}")
print(f"  Status: {raw1.get('incident', {}).get('status', '')}")
print(f"  Affected: {raw1.get('incident', {}).get('affected_services', [])}")
print(f"  Related Changes: {raw1.get('incident', {}).get('related_changes', [])}")

kg1 = step("kg", "GET", f"/kg/incident/{inc1}")
print(f"  KG: {len(kg1.get('nodes',[]))} nodes, {len(kg1.get('edges',[]))} edges")

diag1 = step("diag", "POST", "/copilot/diagnose", json={"incident_id": inc1, "user_id": "ui-user"})
diag1_id = diag1.get("diagnosis_id","")
if diag1:
    print(f"  Diagnosis: {diag1_id}, method={diag1.get('method')}, conf={diag1.get('confidence_summary',0):.2f}")
    for c in diag1.get("candidate_root_causes",[])[:3]:
        print(f"    [{c.get('confidence',0):.0%}] {c.get('cause','')[:80]}")

scr1 = step("scr", "GET", "/script/suggest", params={"incident_id": inc1, "diagnosis_id": diag1_id})
for s in scr1.get("suggestions",[])[:4]:
    print(f"  Script: {s.get('name')} [{s.get('risk_level')}]")

# Execute script
for s in scr1.get("suggestions",[])[:2]:
    sid = s.get("script_id","")
    ex = step("exec", "POST", "/script/execute", json={
        "script_id": sid, "incident_id": inc1, "diagnosis_id": diag1_id,
        "requested_by": "ui-user", "feed_to_copilot": True
    })
    if ex:
        print(f"    Output: {ex.get('output','')[:100]}")

# Chat
ch1 = step("chat", "POST", "/copilot/chat", json={
    "incident_id": inc1, "diagnosis_id": diag1_id, "user_id": "ui-user",
    "message": "MQ Pageset使用率76%还在涨，Queue Depth 219万。最近2603批次投产后今天刚恢复历史数据清理，28张表暂停了23天。请分析可能原因。"
})
if ch1:
    print(f"  Copilot: {ch1.get('response','')[:150]}")

ch2 = step("chat2", "POST", "/copilot/chat", json={
    "incident_id": inc1, "diagnosis_id": diag1_id, "user_id": "ui-user",
    "message": "确认了：单日数据清理量25亿（含试点行8.5亿+恢复15亿+日常6亿），QREP下刷5亿远超日常1亿/小时的吞吐。请给出应急建议。"
})
if ch2:
    print(f"  Copilot: {ch2.get('response','')[:150]}")

# Postmortem
pm1 = step("pm", "POST", f"/incident/{inc1}/postmortem", json={"requested_by": "ui-user", "mark_resolved": True})
if pm1:
    rc = pm1.get("root_cause_conclusion",{})
    kb = pm1.get("knowledge",{})
    print(f"  Postmortem: {pm1.get('postmortem_id')}")
    print(f"  RootCause: {rc.get('cause','')[:120]}")
    print(f"  Knowledge: {len(kb.get('root_cause_rules',[]))} rules, {len(kb.get('warning_signals',[]))} signals")

# Timeline
tl1 = step("tl", "GET", f"/incident/{inc1}/timeline")
for e in tl1.get("timeline",[]):
    print(f"  TL: [{e.get('event_type')}] {e.get('summary','')[:90]}")

# ============================================================
# CASE 2: MCIS (raw alert → simulate scenario)
# ============================================================
section("CASE 2: MCIS→湖南分行 (simulate scenario → raw alert pipeline)")

sim2 = step("sim", "POST", "/incidents/simulate", json={"scenario": "mcis_branch_thirdparty"})
inc2 = sim2.get("incident", {}).get("incident_id", "")
deriv2 = sim2.get("derivation", {})
print(f"  --- Platform Derivation ---")
print(f"  Keywords: {deriv2.get('keywords', [])[:8]}")
print(f"  Matched Systems: {[s['id'] for s in deriv2.get('matched_systems', [])]}")
print(f"  Affected Services: {deriv2.get('matched_system_ids', [])}")
print(f"  Related Changes: {deriv2.get('related_changes', [])}")
print(f"  --- Generated Incident ---")
print(f"  Incident: {inc2}")
print(f"  Summary: {sim2.get('incident', {}).get('summary', '')[:80]}")

diag2 = step("diag", "POST", "/copilot/diagnose", json={"incident_id": inc2, "user_id": "ui-user"})
diag2_id = diag2.get("diagnosis_id","")
if diag2:
    print(f"  Diagnosis: {diag2_id}, conf={diag2.get('confidence_summary',0):.2f}")
    for c in diag2.get("candidate_root_causes",[])[:3]:
        print(f"    [{c.get('confidence',0):.0%}] {c.get('cause','')[:80]}")

scr2 = step("scr", "GET", "/script/suggest", params={"incident_id": inc2, "diagnosis_id": diag2_id})
for s in scr2.get("suggestions",[])[:3]:
    print(f"  Script: {s.get('name')} [{s.get('risk_level')}]")

ch3 = step("chat", "POST", "/copilot/chat", json={
    "incident_id": inc2, "diagnosis_id": diag2_id, "user_id": "ui-user",
    "message": "MCIS到湖南分行成功率45.5%，但其他分行正常。交易链路是手机银行→BOCNET→MCIS→CSP→分行特色→第三方商户。请帮我分析根因可能在哪一层。"
})
if ch3:
    print(f"  Copilot: {ch3.get('response','')[:150]}")

pm2 = step("pm", "POST", f"/incident/{inc2}/postmortem", json={"requested_by": "ui-user", "mark_resolved": True})
if pm2:
    rc = pm2.get("root_cause_conclusion",{})
    print(f"  Postmortem: {pm2.get('postmortem_id')}")
    print(f"  RootCause: {rc.get('cause','')[:120]}")

# ============================================================
# Cross-case
# ============================================================
section("Cross-case: Related Cases")
rel1 = step("rel", "GET", f"/incident/{inc1}/related-cases")
for c in rel1.get("cases",[])[:3]:
    print(f"  [{c.get('similarity_score',0)}] {c.get('summary','')[:80]}")

rel2 = step("rel", "GET", f"/incident/{inc2}/related-cases")
for c in rel2.get("cases",[])[:3]:
    print(f"  [{c.get('similarity_score',0)}] {c.get('summary','')[:80]}")

inv = step("inv", "GET", f"/incident/{inc1}/investigation-state")
if inv:
    for q in ("verified","to_verify","high_risk","excluded"):
        if inv.get(q):
            print(f"  Investigation [{q}]: {len(inv[q])} items")

# ============================================================
section("Summary")
il = step("list", "GET", "/incidents")
if il:
    s = il.get("summary",{})
    print(f"  Total: {s.get('total')}, Open: {s.get('open')}, Resolved: {s.get('resolved')}")
    print(f"  Services: {s.get('services')}")

tl2 = step("tl", "GET", f"/incident/{inc2}/timeline")
for e in tl2.get("timeline",[]):
    print(f"  TL: [{e.get('event_type')}] {e.get('summary','')[:90]}")

print(f"\n{'='*60}")
print(f"  RESULTS: {PASS} passed, {FAIL} failed ({PASS+FAIL} total)")
print(f"{'='*60}")
if FAIL:
    print("  WARNING: Some steps failed!")
else:
    print("  SUCCESS: All pipeline steps passed!")
