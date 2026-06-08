"""E2E Demo Flow Test — simulates the complete user journey.

Flow:
1. Simulate an incident → auto-triggers pipeline
2. Check /incident/{id} → enriched with KG, diagnosis, cases, scripts
3. Check timeline → meaningful events (not just "会话已生成")
4. Ask Copilot → Skill-aware response
5. Execute a script → auto-feeds back to Copilot
6. Generate postmortem → Agent-driven report
"""

import urllib.request
import json
import sys
import time

BASE = "http://localhost:8000"
PORT = sys.argv[1] if len(sys.argv) > 1 else "8000"
BASE = f"http://localhost:{PORT}"

def api(path, method="GET", body=None, timeout=90):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())

def check(label, cond, detail=""):
    status = "✅" if cond else "❌"
    msg = f"{status} {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return cond

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

ok = True

# =========================================================================
# STEP 1: Simulate an incident (BOCS-DNF scenario — has upstream/downstream)
# =========================================================================
section("STEP 1: Simulate Incident → Auto-Trigger Pipeline")

resp = api("/incidents/simulate", "POST", {"scenario": "bocs_dnf_sync_delay"})
inc = resp.get("incident", {})
inc_id = inc.get("incident_id", "")
print(f"Incident: {inc_id}")
print(f"Summary: {inc.get('summary', 'N/A')[:80]}")
print(f"Pipeline triggered: {resp.get('pipeline_triggered', False)}")

ok &= check("Incident created", bool(inc_id), inc_id)
ok &= check("Pipeline auto-triggered", resp.get("pipeline_triggered") == True)

# Wait a moment for pipeline to complete
time.sleep(1)

# =========================================================================
# STEP 2: Get enriched incident
# =========================================================================
section("STEP 2: Get Incident → Enriched Context")

inc = api(f"/incident/{inc_id}")
kg = inc.get("kg_context", {})

# Check KG context
services = kg.get("services", [])
upstream = kg.get("upstream", [])
downstream = kg.get("downstream", [])
dep_summary = kg.get("dependency_summary", "")

print(f"Services affected: {len(services)}")
print(f"Upstream dependencies: {len(upstream)} — {[u.get('name','?') for u in upstream[:3]]}")
print(f"Downstream impact: {len(downstream)} — {[d.get('name','?') for d in downstream[:3]]}")
print(f"Dependency summary: {dep_summary[:120]}")

ok &= check("KG context built", len(services) > 0)
ok &= check("Upstream dependencies found", len(upstream) > 0, 
           f"Found {len(upstream)} upstream systems")
ok &= check("Downstream impact found", len(downstream) > 0,
           f"Found {len(downstream)} downstream systems")
ok &= check("Dependency summary present", bool(dep_summary))

# Check auto diagnosis
diag = inc.get("auto_diagnosis", {})
print(f"\nAuto-diagnosis: {diag.get('diagnosis_id', 'NONE')}")
print(f"Active skills: {inc.get('active_skills', [])}")
print(f"Primary skill: {inc.get('primary_skill', 'N/A')}")
print(f"Related cases: {len(inc.get('related_cases', []))}")
print(f"Suggested scripts: {len(inc.get('suggested_scripts', []))}")

ok &= check("Auto-diagnosis present", bool(diag.get("diagnosis_id")))
ok &= check("Active skills populated", len(inc.get("active_skills", [])) > 0)
ok &= check("Related cases found", len(inc.get("related_cases", [])) > 0)
ok &= check("Scripts suggested", len(inc.get("suggested_scripts", [])) > 0)

# =========================================================================
# STEP 3: Check timeline → meaningful events
# =========================================================================
section("STEP 3: Timeline → Meaningful Events")

tl = api(f"/incident/{inc_id}/timeline")
events = tl.get("timeline", [])
print(f"Total timeline events: {len(events)}")
for e in events:
    print(f"  [{e.get('event_type')}] {e.get('summary', '')[:100]}")

ok &= check("Timeline has events", len(events) >= 4, f"{len(events)} events")
ok &= check("Has KG context event", any("知识图谱" in e.get("summary", "") for e in events))
ok &= check("Has diagnosis event", any("诊断" in e.get("summary", "") for e in events))
ok &= check("Has 'ready' event", any("准备就绪" in e.get("summary", "") for e in events))
ok &= check("Events are meaningful", 
           not any("会话已生成" in e.get("summary", "") for e in events),
           "No useless '会话已生成' messages")

# =========================================================================
# STEP 4: Copilot Chat → Skill-aware
# =========================================================================
section("STEP 4: Copilot Chat → Skill-Aware Response")

# Skip if LLM not configured (it will use rule-based, which is also skill-aware now)
resp = api("/copilot/chat", "POST", {
    "incident_id": inc_id,
    "diagnosis_id": diag.get("diagnosis_id", ""),
    "user_id": "ui-user",
    "message": "日志里有大量MQ连接超时，帮我分析一下"
})

print(f"Response: {resp.get('response', 'N/A')[:120]}")
print(f"Active skills: {resp.get('active_skills', [])}")
print(f"Primary skill: {resp.get('primary_skill', 'N/A')}")
print(f"Agent timeline: {len(resp.get('agent_timeline', []))} entries")

ok &= check("Chat response received", bool(resp.get("response")))
ok &= check("Skill context in response", len(resp.get("active_skills", [])) > 0)
ok &= check("Agent timeline present", len(resp.get("agent_timeline", [])) > 0)

# Check if response is skill-tagged (rule-based mode)
if resp.get("method") == "rule_based" and "[" in resp.get("response", ""):
    ok &= check("Response skill-tagged", True, "Rule-based response has skill tag")
    print(f"  Skill tag detected in response")

# =========================================================================
# STEP 5: Execute a script → auto-feedback to Copilot
# =========================================================================
section("STEP 5: Script Execute → Auto-Feedback to Copilot")

scripts = inc.get("suggested_scripts", [])
if scripts:
    script_id = scripts[0].get("script_id", "")
    script_name = scripts[0].get("name", "")
    print(f"Executing: {script_name}")
    
    resp = api("/script/execute", "POST", {
        "script_id": script_id,
        "requested_by": "ui-user",
        "incident_id": inc_id,
        "diagnosis_id": diag.get("diagnosis_id", ""),
        "feed_to_copilot": True,
        "lifecycle_type": "once",
    })
    
    print(f"Output: {resp.get('output', 'N/A')[:100]}")
    print(f"Conclusion: {resp.get('conclusion', 'N/A')[:120]}")
    print(f"Fed to Copilot: {resp.get('fed_to_copilot', False)}")
    
    ok &= check("Script executed", resp.get("status") == "success")
    ok &= check("Result fed to Copilot", resp.get("fed_to_copilot") == True)
    
    # Check timeline updated with execution result
    time.sleep(0.5)
    tl2 = api(f"/incident/{inc_id}/timeline")
    events2 = tl2.get("timeline", [])
    
    has_exec_event = any("脚本执行" in e.get("summary", "") or 
                          "根因假设已更新" in e.get("summary", "") 
                          for e in events2)
    ok &= check("Timeline has execution event", has_exec_event)
    for e in events2[-3:]:
        print(f"  [{e.get('event_type')}] {e.get('summary', '')[:100]}")
else:
    print("⚠ No scripts to test — skipping")

# =========================================================================
# STEP 6: Postmortem → Agent-driven
# =========================================================================
section("STEP 6: Postmortem → Agent-Driven Report")

# First mark as resolved
resp = api(f"/incident/{inc_id}/postmortem", "POST", {
    "requested_by": "ui-user",
    "mark_resolved": True,
})

pm_id = resp.get("postmortem_id", "")
print(f"Postmortem ID: {pm_id}")
print(f"Root cause: {resp.get('root_cause_conclusion', {}).get('cause', 'N/A')[:80]}")
print(f"Agent used: {resp.get('agent_name', resp.get('skill_used', 'N/A'))}")
print(f"Knowledge distilled: {'knowledge' in resp}")

ok &= check("Postmortem generated", bool(pm_id))
ok &= check("Agent/skill recorded", bool(resp.get("agent_name") or resp.get("skill_used")))
ok &= check("Root cause conclusion", bool(resp.get("root_cause_conclusion", {}).get("cause")))
ok &= check("Knowledge distillation", "knowledge" in resp)

# =========================================================================
# SUMMARY
# =========================================================================
section("SUMMARY")
if ok:
    print("✅ ALL DEMO FLOW TESTS PASSED")
    print()
    print("Demonstration flow verified:")
    print("  1. Incident arrives → Pipeline auto-triggers")
    print("  2. KG context built (upstream/downstream dependencies)")
    print("  3. Log analysis, case matching, skill-aware diagnosis")
    print("  4. Timeline has meaningful events (no '会话已生成')")
    print("  5. Copilot responds with skill context")
    print("  6. Script execution feeds back → updates diagnosis + timeline")
    print("  7. Postmortem generated by agent with knowledge distillation")
else:
    print("❌ SOME TESTS FAILED")

sys.exit(0 if ok else 1)
