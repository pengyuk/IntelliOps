#!/usr/bin/env python3
"""IntelliOps Live Demo - From Alert to Postmortem"""
import json, sys, time, urllib.request
from typing import Any, Dict, Optional

BASE = "http://localhost:8000"
SCENARIO = "bocs_dnf_sync_delay"

def api(path, method="GET", body=None, timeout=120):
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode()[:200]}")
        raise

def step(title):
    print(f"\n{'='*72}\n  >> {title}\n{'='*72}")

def bullet(label, value="", indent=2):
    p = " " * indent
    if value:
        print(f"{p}* {label}: {value}")
    else:
        print(f"{p}* {label}")

def step1_receive_alert():
    step("Step 1: Alert Ingestion & Auto-Resolution")
    print("  >> Simulating raw alert (severity + source + content only)...")
    result = api("/incidents/simulate", "POST", {"scenario": SCENARIO, "severity": 4, "summary": ""}, timeout=180)
    inc = result.get("incident", {})
    inc_id = inc.get("incident_id", "")
    pd = result.get("platform_derived", {})
    print(f"\n  OK Event Created:")
    bullet("Incident ID", inc_id)
    bullet("Severity", f"P{inc.get('severity','')}")
    bullet("Summary", inc.get("summary","")[:120])
    bullet("Derived Summary", pd.get("derived_summary","")[:120])
    bullet("Matched Systems", pd.get("matched_systems",[]))
    bullet("Related Changes", pd.get("related_changes",[]))
    print("\n  >> Key: Raw alert -> auto parse (text analysis + system matching)")
    input("  Press Enter for next step...")
    return inc_id, result

def step2_kg_context(inc_id):
    step("Step 2: Knowledge Graph Dependency Analysis")
    inc = api(f"/incident/{inc_id}")
    kg = inc.get("kg_context", {})
    print("  >> Affected Systems:")
    for s in kg.get("services",[]):
        bullet(f"{s.get('name',s.get('id','?'))} ({s.get('type','?')})", indent=4)
    print("\n  >> Upstream Dependencies (what this depends on):")
    for u in kg.get("upstream",[]):
        bullet(u.get('name',u.get('id','?')), indent=4)
    print("\n  >> Downstream Impact (who depends on this):")
    for d in kg.get("downstream",[]):
        bullet(d.get('name',d.get('id','?')), indent=4)
    print("\n  >> Key: BFS graph traversal for dependency discovery + blast radius")
    input("  Press Enter for next step...")

def step3_auto_diagnosis(inc_id):
    step("Step 3: Root Cause Diagnosis (Reasoner + Credibility)")
    diag = api("/copilot/diagnose", "POST", {"incident_id": inc_id, "user_id": "ui-user"}, timeout=180)
    print(f"  Diagnosis ID: {diag.get('diagnosis_id','')}")
    print(f"  Method: {diag.get('method','')}")
    print(f"  Confidence: {diag.get('confidence_summary',0):.2f}")
    candidates = diag.get("candidate_root_causes",[])
    print(f"\n  >> Candidate Root Causes ({len(candidates)}):")
    for i, c in enumerate(candidates, 1):
        print(f"\n    -- Candidate #{i} --")
        bullet("Cause", c.get("cause","?")[:120], 4)
        bullet("Confidence", f"{c.get('confidence',0):.2f}", 4)
        bullet("Level", c.get("confidence_level","?"), 4)
    for j, ev in enumerate(diag.get("evidence",[]), 1):
        print(f"    Evidence #{j}: {str(ev)[:100]}")
    print(f"\n  >> Active Skills: {diag.get('active_skills',[])}")
    print(f"  >> Primary Skill: {diag.get('primary_skill','N/A')}")
    print("\n  >> Key: Multi-step causal reasoning + evidence chain + credibility scoring")
    input("  Press Enter for next step...")
    return diag

def step4_related_cases(inc_id):
    step("Step 4: Historical Case Matching (Vector Search)")
    related = api(f"/incident/{inc_id}/related-cases")
    cases = related.get("related_cases",[])
    print(f"\n  >> Found {len(cases)} similar historical cases:")
    for i, case in enumerate(cases[:5], 1):
        print(f"\n    -- Case #{i} --")
        bullet("Title", case.get("title", case.get("name","?"))[:80], 4)
        bullet("Similarity", case.get("similarity",""), 4)
        bullet("Root Cause", str(case.get("root_cause","?"))[:80], 4)
    print("\n  >> Key: Vector search + semantic matching of past postmortems")
    input("  Press Enter for next step...")

def step5_script(inc_id, diag):
    step("Step 5: Automated Remediation Scripts (Harness)")
    sd = api(f"/script/suggest?incident_id={inc_id}")
    scripts = sd.get("scripts",[])
    print(f"  >> Suggested {len(scripts)} scripts:")
    for i, s in enumerate(scripts[:5], 1):
        bullet(f"#{i} {s.get('name','?')}", indent=4)
        bullet(f"   Risk", s.get("risk_level","?"), 4)
    if scripts:
        sid = scripts[0].get("script_id","")
        print(f"\n  >> Executing: {scripts[0].get('name','unknown')}")
        print("  >> Pre-execution verification...")
        api("/script/verify","POST",{"script_id":sid,"user_id":"ui-user"},timeout=30)
        print("  >> Executing script...")
        er = api("/script/execute","POST",{"script_id":sid,"requested_by":"ui-user","incident_id":inc_id,"diagnosis_id":diag.get("diagnosis_id",""),"feed_to_copilot":True,"lifecycle_type":"once"},timeout=60)
        bullet("Status", er.get("status","?"))
        bullet("Conclusion", str(er.get("conclusion",""))[:120])
        bullet("Fed back to Copilot", er.get("fed_to_copilot",False))
    print("\n  >> Key: Pre-verify -> Execute -> Audit trail -> Feed back to Copilot")
    input("  Press Enter for next step...")

print("IntelliOps Live Demo module loaded.")

def step6_copilot(inc_id, diag):
    step("Step 6: Stateful Copilot Multi-Turn Chat (Skill Routing)")
    did = diag.get("diagnosis_id","")
    questions = [
        "Check MQ connection timeouts in logs",
        "Has this root cause occurred before? Any similar cases?",
        "What should we do now? Give me steps",
    ]
    for qi, q in enumerate(questions, 1):
        print(f"\n  >> Round {qi}: User asks: {q}")
        cr = api("/copilot/chat","POST",{"incident_id":inc_id,"diagnosis_id":did,"user_id":"ui-user","message":q},timeout=180)
        answer = cr.get("response","")
        bullet("Copilot response", f"{answer[:200]}...")
        if cr.get("active_skills"):
            bullet("Active Skills", cr["active_skills"])
        if cr.get("primary_skill"):
            bullet("Primary Skill", cr["primary_skill"])
    print("\n  >> Key: Stateful multi-turn + Skill routing + Agent orchestration")
    input("  Press Enter for next step...")

def step7_state(inc_id):
    step("Step 7: Investigation State Machine (4-Quadrant)")
    state = api(f"/incident/{inc_id}/investigation-state")
    qs = state.get("quadrants",{})
    labels = {"verified":"Verified","to_verify":"To Verify","high_risk":"High Priority","excluded":"Excluded"}
    for qname, items in qs.items():
        label = labels.get(qname, qname)
        item_list = items if isinstance(items, list) else []
        print(f"  {label} ({len(item_list)} items):")
        for item in item_list[:4]:
            name = item.get("name", item.get("item", str(item)[:60]))
            bullet(name, indent=4)
    print("\n  >> Key: Transparent triage progress + risk-prioritized investigation")
    input("  Press Enter for next step...")

def step8_postmortem(inc_id):
    step("Step 8: Auto Postmortem & Knowledge Distillation")
    pm = api(f"/incident/{inc_id}/postmortem","POST",{"requested_by":"ui-user","mark_resolved":True},timeout=180)
    pm_id = pm.get("postmortem_id","")
    print(f"  Postmortem ID: {pm_id}")
    bullet("Root Cause", pm.get("root_cause_conclusion",{}).get("cause","")[:120])
    bullet("Agent Used", pm.get("agent_name",pm.get("skill_used","N/A")))
    tasks = pm.get("improvement_tasks",[])
    if tasks:
        print(f"\n  >> Improvement Tasks ({len(tasks)}):")
        for i, t in enumerate(tasks[:5], 1):
            bullet(f"#{i} {t.get('title','?')} (Priority: {t.get('priority','?')})")
    kn = pm.get("knowledge",{})
    if kn:
        rules = kn.get("rules",kn.get("patterns",[]))
        if rules:
            print(f"\n  >> Knowledge Distilled: {len(rules)} rules/patterns")
            for r in rules[:3]:
                bullet(f"{r.get('title',r.get('name',str(r)[:60]))}", indent=4)
    print("\n  >> Key: Auto postmortem + Agent-driven report + Knowledge distillation")
    input("  Press Enter for next step...")
    return pm_id

def step9_knowledge(pm_id):
    step("Step 9: Knowledge Base & High-Frequency Pattern Aggregation")
    try:
        kn = api(f"/postmortem/{pm_id}/knowledge")
        print("  >> Knowledge Assets:")
        for k, v in kn.items():
            if isinstance(v, list):
                print(f"     {k}: {len(v)} items")
                for item in v[:3]:
                    print(f"       - {str(item)[:80]}")
    except Exception:
        print("  (knowledge endpoint not available)")
    print("\n  >> Running high-frequency pattern aggregation:")
    try:
        agg = api("/knowledge/run-aggregation","POST",{"user_id":"admin"},timeout=60)
        pats = agg.get("patterns",[])
        print(f"     Found {len(pats)} high-frequency patterns")
        for p in pats[:3]:
            print(f"       - {p.get('name',p.get('pattern','?'))}: {p.get('frequency',p.get('count','?'))} times")
    except Exception:
        print("  (aggregation endpoint not available)")
    print("\n  >> Key: Knowledge auto-sedimentation -> prevent recurrence -> accelerate onboarding")
    input("  Press Enter for next step...")

def step10_panorama():
    step("Step 10: System Panorama")
    h = api("/health")
    print("  >> System Health:")
    bullet("Status", h.get("status",""))
    bullet("LLM Ready", h.get("llm",{}).get("configured",False))
    bullet("Skills", h.get("skills",{}).get("count",0))
    bullet("Agents", h.get("agents",{}).get("count",0))
    ags = api("/agents")
    print(f"\n  >> Agents ({ags.get('total',0)}):")
    for a in ags.get("agents",[]):
        loaded = "V" if a.get("skill_loaded") else "X"
        print(f"     {a.get('icon','')} {a.get('display_name','?')} [{loaded}]")
    sk = api("/skills")
    print(f"\n  >> Skills ({sk.get('total',0)}):")
    for s in sk.get("skills",[]):
        print(f"     {s.get('name','?')} -- {s.get('meta',{}).get('description','')[:60]}")
    print("\n  >> Key: Multi-Agent orchestration + Skill plugin system + rich scenarios")
    input("  Press Enter for summary...")


def summary():
    step("Demo Summary")
    print("")
    print("  ======================================================================")
    print("                  IntelliOps Cognitive Emergency System - Overview")
    print("  ======================================================================")
    print("")
    print("  Alert Ingestion Layer")
    print("    - Raw alert -> auto parse (text analysis + system matching)")
    print("    - 6 real-world financial scenario templates")
    print("")
    print("  Knowledge Graph Layer")
    print("    - BFS dependency discovery (upstream/downstream/blast radius)")
    print("    - Multi-hop change/alert/service correlation")
    print("    - Vector search for similar historical cases")
    print("")
    print("  LLM Cognitive Layer (Core Differentiation)")
    print("    - Root Cause Reasoner - multi-step causal reasoning")
    print("    - Log Analyzer - auto summarization + anomaly detection")
    print("    - Credibility Framework - confidence + evidence chain + risk levels")
    print("    - Investigation State Machine - 4-quadrant transparent progress")
    print("")
    print("  Collaboration Layer")
    print("    - Incident Copilot - stateful multi-turn diagnosis")
    print("    - 9 professional Skills with smart routing")
    print("    - Agent Orchestrator - multi-agent coordination")
    print("")
    print("  Automation Layer")
    print("    - Harness - pre-verify + execute + audit trail")
    print("    - Execution results auto-feed back to diagnosis context")
    print("")
    print("  Postmortem & Learning Loop")
    print("    - Auto postmortem report (Agent-driven)")
    print("    - Knowledge Distiller - fault -> rules/SOP/improvement tasks")
    print("    - High-frequency pattern aggregation -> auto Skill updates")
    print("    - Incident Simulator - drill system")
    print("")
    print("  Engineering Foundation")
    print("    - SQLite persistence (9 tables) | Audit logs + RBAC")
    print("    - 50+ REST APIs + WebSocket | Docker deployment")
    print("  ======================================================================")
    print("")

def main():
    print("")
    print("  ======================================================================")
    print("      IntelliOps Live Demo - From Alert to Postmortem (End-to-End)")
    print("  ======================================================================")
    print("")
    inc_id, sim = step1_receive_alert()
    step2_kg_context(inc_id)
    diag = step3_auto_diagnosis(inc_id)
    step4_related_cases(inc_id)
    step5_script(inc_id, diag)
    step6_copilot(inc_id, diag)
    step7_state(inc_id)
    pm_id = step8_postmortem(inc_id)
    step9_knowledge(pm_id)
    step10_panorama()
    summary()
    print(f"\n  Demo Complete! Incident: {inc_id}, Postmortem: {pm_id}")
    print(f"  UI: {BASE}/ui/")

if __name__ == "__main__":
    main()
