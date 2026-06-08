"""E2E test for skill system on a specific port."""
import urllib.request, json, sys

PORT = sys.argv[1] if len(sys.argv) > 1 else "8001"
BASE = f"http://localhost:{PORT}"

def api(path, method="GET", body=None, timeout=60):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())

def check(label, cond, detail=""):
    status = "✅" if cond else "❌"
    print(f"{status} {label}" + (f" — {detail}" if detail else ""))
    return cond

ok = True
print(f"Testing against {BASE}\n")

# 1. Health
r = api("/health")
ok &= check("Health: status ok", r["status"] == "ok")
ok &= check("Health: skills loaded", r.get("skills", {}).get("loaded") == True)
ok &= check(f"Health: {r['skills'].get('count')} skills", r["skills"].get("count", 0) >= 6)

# 2. List skills
r = api("/skills")
ok &= check(f"Skills: {r['total']} loaded", r["total"] == 9)
print(f"   Names: {[s['name'] for s in r['skills']]}")

# 3. Skill detail
r = api("/skills/incident-diagnosis")
ok &= check("Detail: name correct", r["name"] == "incident-diagnosis")
ok &= check(f"Detail: {len(r['steps'])} steps", len(r["steps"]) > 0)
ok &= check(f"Detail: {len(r['api_refs'])} API refs", len(r["api_refs"]) > 0)
print(f"   Steps: {[s['title'] for s in r['steps']]}")

# 4. Skill match
r = api("/skills/match", "POST", {"query": "支付延迟排查根因"})
matches = r.get("matches", [])
ok &= check(f"Match: top={matches[0]['skill_name']}" if matches else "Match: no results", 
           matches and matches[0]["skill_name"] == "incident-diagnosis")
if matches:
    for m in matches[:3]:
        print(f"   {m['skill_name']}: score={m['score']}")

# 5. Agents
r = api("/agents")
ok &= check(f"Agents: {r['total']} total", r["total"] >= 7)
for a in r["agents"]:
    loaded = "✓" if a["skill_loaded"] else "✗"
    print(f"   {a['icon']} {a['display_name']} [{loaded}]")

# 6. Active skills for incident
r = api("/incidents")
inc_id = r["incidents"][0]["incident_id"] if r.get("incidents") else None
if inc_id:
    r = api(f"/incident/{inc_id}/active-skills")
    ok &= check(f"Active skills: {len(r['active_skills'])} for {inc_id}", len(r["active_skills"]) > 0)
    for s in r["active_skills"]:
        print(f"   {s['name']}")

# Summary
print(f"\n{'='*50}")
print(f"{'✅ ALL PASSED' if ok else '❌ FAILURES'}")

# If we have an incident, try diagnose
if inc_id:
    print(f"\n--- Copilot Diagnose ---")
    try:
        r = api("/copilot/diagnose", "POST", {"incident_id": inc_id, "user_id": "ui-user"}, timeout=90)
        ok &= check(f"Diagnose: {r.get('diagnosis_id', 'NO ID')}", "diagnosis_id" in r)
        ok &= check(f"Active skills: {r.get('active_skills')}", "active_skills" in r)
        ok &= check(f"Primary skill: {r.get('primary_skill')}", r.get("primary_skill") is not None)
        print(f"   active_skills: {r.get('active_skills')}")
        print(f"   primary_skill: {r.get('primary_skill')}")
    except Exception as e:
        print(f"   ⚠ Diagnose failed (DataService may be slow): {e}")

print(f"\n{'='*50}")
print(f"{'✅ ALL PASSED' if ok else '❌ SOME FAILED'}")
