"""End-to-end test for Skill/Agent system via HTTP API."""
import urllib.request
import json

BASE = "http://localhost:8000"

def api(path, method="GET", body=None, timeout=60):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def test(label, result, checks=None):
    status = "✅" if not result.get("error") else "❌"
    print(f"{status} {label}")
    if result.get("error"):
        print(f"   Error: {result['error']}")
        return False
    if checks:
        for check_name, check_fn in checks.items():
            try:
                ok = check_fn(result)
                print(f"   {'✅' if ok else '❌'} {check_name}")
                if not ok:
                    return False
            except Exception as e:
                print(f"   ❌ {check_name}: {e}")
                return False
    return True


def main():
    all_ok = True
    
    # 1. Health check (includes skills)
    print("\n--- 1. Health Check ---")
    r = api("/health")
    all_ok &= test("Health endpoint", r, {
        "status ok": lambda r: r.get("status") == "ok",
        "skills loaded": lambda r: r.get("skills", {}).get("loaded") == True,
        "skills count >= 6": lambda r: r.get("skills", {}).get("count", 0) >= 6,
    })
    
    # 2. List all skills
    print("\n--- 2. List Skills ---")
    r = api("/skills")
    all_ok &= test("List skills", r, {
        "has skills array": lambda r: "skills" in r,
        "skill count = 9": lambda r: r.get("total") == 9,
    })
    
    # 3. Get specific skill
    print("\n--- 3. Get Skill Detail ---")
    r = api("/skills/incident-diagnosis")
    all_ok &= test("Get incident-diagnosis", r, {
        "has name": lambda r: r.get("name") == "incident-diagnosis",
        "has steps": lambda r: len(r.get("steps", [])) > 0,
        "has api_refs": lambda r: len(r.get("api_refs", [])) > 0,
    })
    if not r.get("error"):
        print(f"   Steps: {[s['title'] for s in r.get('steps', [])]}")
        print(f"   APIs: {r.get('api_refs', [])[:5]}")
    
    # 4. Match skills by query
    print("\n--- 4. Match Skills ---")
    r = api("/skills/match", method="POST", body={"query": "支付延迟，排查根因"})
    all_ok &= test("Match skills", r, {
        "has matches": lambda r: len(r.get("matches", [])) > 0,
        "top is incident-diagnosis": lambda r: r["matches"][0]["skill_name"] == "incident-diagnosis" if r.get("matches") else False,
    })
    if r.get("matches"):
        for m in r["matches"][:3]:
            print(f"   {m['skill_name']}: score={m['score']}")
    
    # 5. List agents
    print("\n--- 5. List Agents ---")
    r = api("/agents")
    all_ok &= test("List agents", r, {
        "has agents": lambda r: len(r.get("agents", [])) > 0,
    })
    for a in r.get("agents", [])[:5]:
        loaded = "✓" if a.get("skill_loaded") else "✗"
        print(f"   {a['icon']} {a['display_name']} ({a['agent_name']}) [{loaded}]")
    
    # 6. Get active skills for an incident
    print("\n--- 6. Active Skills for Incident ---")
    r = api("/incidents")
    inc_id = r.get("incidents", [{}])[0].get("incident_id", "")
    if inc_id:
        r = api(f"/incident/{inc_id}/active-skills")
        all_ok &= test("Active skills", r, {
            "has active_skills": lambda r: len(r.get("active_skills", [])) > 0,
        })
        for s in r.get("active_skills", []):
            print(f"   {s['name']}: {s['description'][:80]}")
    
    # 7. Copilot diagnose with skill context
    print("\n--- 7. Copilot Diagnose (with Skill context) ---")
    r = api("/copilot/diagnose", method="POST", body={
        "incident_id": inc_id,
        "user_id": "ui-user"
    })
    all_ok &= test("Copilot diagnose", r, {
        "has diagnosis_id": lambda r: "diagnosis_id" in r,
        "has active_skills": lambda r: "active_skills" in r,
        "has primary_skill": lambda r: "primary_skill" in r,
    })
    if not r.get("error"):
        print(f"   Active Skills: {r.get('active_skills', [])}")
        print(f"   Primary Skill: {r.get('primary_skill', 'N/A')}")
        if r.get("skill_suggestions"):
            for s in r["skill_suggestions"]:
                print(f"   💡 {s['skill']}: {s['step']}")
    
    # 8. Copilot chat with skill routing
    print("\n--- 8. Copilot Chat (with Skill routing) ---")
    r2 = api("/copilot/chat", method="POST", body={
        "incident_id": inc_id,
        "diagnosis_id": r.get("diagnosis_id", ""),
        "user_id": "ui-user",
        "message": "日志里有很多timeout错误"
    })
    all_ok &= test("Copilot chat", r2, {
        "has response": lambda r: "response" in r,
        "has active_skills": lambda r: "active_skills" in r,
    })
    if not r2.get("error"):
        print(f"   Response: {r2.get('response', '')[:100]}...")
        print(f"   Active Skills: {r2.get('active_skills', [])}")
        print(f"   Primary Skill: {r2.get('primary_skill', 'N/A')}")
        if r2.get("agent_timeline"):
            for e in r2["agent_timeline"]:
                print(f"   📍 {e['agent']}: {e['summary']}")
    
    # Summary
    print("\n" + "=" * 60)
    if all_ok:
        print("✅ ALL TESTS PASSED")
    else:
        print("❌ SOME TESTS FAILED")
    print("=" * 60)
    return all_ok


if __name__ == "__main__":
    import sys
    ok = main()
    sys.exit(0 if ok else 1)
