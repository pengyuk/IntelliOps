"""
End-to-end demo test: starts server, runs all 10 demo steps, reports gaps.
Usage: python scripts/test_demo_e2e.py
"""
import subprocess, sys, time, json, urllib.request, threading, os

os.environ['SKIP_DB_INIT'] = '1'
os.environ['SKIP_DATA_LOAD'] = '1'

BASE = 'http://127.0.0.1:8000'
errors = []

# Start server in background
print('[SETUP] Starting backend server...')
server = subprocess.Popen(
    [sys.executable, '-m', 'uvicorn', 'src.backend.app:app', '--host', '127.0.0.1', '--port', '8000'],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    cwd=r'd:\大模型\IntelliOps'
)

# Wait for server to be ready
for i in range(30):
    try:
        r = urllib.request.urlopen(BASE + '/health', timeout=2)
        if r.status == 200:
            print(f'[SETUP] Server ready (attempt {i+1})')
            break
    except:
        time.sleep(1)
else:
    print('[SETUP] Server failed to start')
    server.kill()
    sys.exit(1)

def api(method, path, data=None, timeout=10):
    url = BASE + path
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'}, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(r.read())
    except Exception as e:
        return {'_error': str(e)}

def check(step, field, value, min_expected=None):
    ok = bool(value) if min_expected is None else len(value) >= min_expected if isinstance(value, (list, dict)) else bool(value)
    status = 'OK' if ok else 'MISSING'
    if not ok:
        errors.append(f'Step {step}: {field} missing/empty')
    print(f'  [{status}] {field}: {str(value)[:80]}')

# ============ STEP 1: Ingest raw alert ============
print('\n=== STEP 1: Ingest raw alert ===')
r1 = api('POST', '/ingest/raw-alert', {
    'severity': 4, 'source': 'BPPM',
    'content': 'MQ Pageset 76% trigger Level-1 alarm. 2603 batch historical cleanup causing QREP backlog. C-DBC success rate 98%.'
})
inc_id = r1.get('incident', {}).get('incident_id', '')
check(1, 'incident_id', inc_id)
check(1, 'pipeline_triggered', r1.get('pipeline_triggered'))
kw = r1.get('derivation', {}).get('keywords', [])
check(1, 'keywords', kw, 1)
sys_ids = r1.get('derivation', {}).get('matched_system_ids', [])
check(1, 'matched_systems', sys_ids)
print(f'    incident_id = {inc_id}')

# ============ STEP 2: KG context ============
print('\n=== STEP 2: KG context ===')
r2 = api('GET', f'/incident/{inc_id}')
kg = r2.get('kg_context', {})
check(2, 'kg_context', kg)
check(2, 'services', kg.get('services', []))
up = kg.get('upstream', [])
down = kg.get('downstream', [])
check(2, 'upstream', up)
check(2, 'downstream', down)
check(2, 'dependency_summary', kg.get('dependency_summary', ''))
if up:
    print(f'    upstream: {[u.get("name","?") for u in up]}')
if down:
    print(f'    downstream: {[d.get("name","?") for d in down]}')
has_auto_diag = 'auto_diagnosis' in r2
print(f'    has_auto_diagnosis: {has_auto_diag}')

# ============ STEP 3: Async diagnose ============
print('\n=== STEP 3: Async diagnose ===')
r3 = api('POST', '/copilot/diagnose', {'incident_id': inc_id, 'user_id': 'ui-user'})
diag_id = r3.get('diagnosis_id', '')
check(3, 'diagnosis_id', diag_id)
check(3, 'status queued', r3.get('status') == 'queued')
time.sleep(2)
poll = api('GET', f'/copilot/diagnose/{diag_id}')
check(3, 'poll status', poll.get('status'))
check(3, 'poll progress', poll.get('progress'))
check(3, 'poll step', poll.get('step'))
print(f'    diag_id={diag_id} poll_status={poll.get("status")} progress={poll.get("progress")}%')

# ============ STEP 4: Knowledge base ============
print('\n=== STEP 4: Knowledge base ===')
r4a = api('GET', f'/incident/{inc_id}/related-cases?limit=5')
r4b = api('GET', f'/incident/{inc_id}/knowledge-assets')
r4c = api('GET', '/knowledge/high-frequency-patterns')
check(4, 'related_cases', r4a.get('cases', []))
check(4, 'knowledge_assets', r4b.get('assets', []))
check(4, 'high_freq_patterns', r4c.get('patterns', []))
print(f'    cases={len(r4a.get("cases",[]))} assets={len(r4b.get("assets",[]))} patterns={len(r4c.get("patterns",[]))}')

# ============ STEP 5: Scripts ============
print('\n=== STEP 5: Scripts ===')
r5 = api('GET', f'/script/suggest?incident_id={inc_id}')
suggestions = r5.get('suggestions', []) or []
check(5, 'script suggestions', suggestions, 1)
for s in suggestions[:3]:
    topo = ' TOPO' if s.get('category') == 'kg_aware' else ''
    print(f'    - {s.get("name","?")[:50]} risk={s.get("risk_level")}{topo}')
    if s.get('topology_hint'):
        print(f'      hint: {s["topology_hint"]}')

# ============ STEP 6: Discussion ============
print('\n=== STEP 6: Discussion ===')
r6 = api('POST', f'/incident/{inc_id}/discussion', {
    'author': 'dev-user', 'message': 'Dev found QREP consumer thread stuck after 2603 batch',
    'message_type': 'development'
})
check(6, 'discussion sent', r6.get('comment_id'))
msgs = api('GET', f'/incident/{inc_id}/discussion')
check(6, 'discussion list', msgs.get('messages', []), 1)
print(f'    messages={len(msgs.get("messages",[]))}')

# ============ STEP 7: Investigation state ============
print('\n=== STEP 7: Investigation state ===')
r7 = api('GET', f'/incident/{inc_id}/investigation-state')
check(7, 'investigation state', r7)
print(f'    state keys: {list((r7 or {}).keys())[:5]}')

# ============ STEP 8: Postmortem ============
print('\n=== STEP 8: Postmortem ===')
r8 = api('POST', f'/incident/{inc_id}/postmortem', {
    'requested_by': 'ui-user', 'mark_resolved': True
}, timeout=60)
check(8, 'postmortem_id', r8.get('postmortem_id'))
has_k = 'knowledge' in r8
check(8, 'has knowledge', has_k)
k = r8.get('knowledge', {})
if k and k.get('status') != 'skipped':
    check(8, 'root_cause_rules', k.get('root_cause_rules', []))
    check(8, 'sop_templates', k.get('sop_templates', []))
    check(8, 'key_learnings', k.get('key_learnings', []))
pe = r8.get('_pipeline_extras', {})
if pe:
    ds = pe.get('dedup_summary', {})
    print(f'    pipeline: dedup_merged={ds.get("merged",0)} agg={pe.get("aggregation_count",0)} skill_updates={len(pe.get("skill_updates",[]))}')

# ============ STEP 9: Skills ============
print('\n=== STEP 9: Skills & aggregation ===')
r9a = api('GET', '/knowledge/skill-update-log')
r9b = api('GET', '/skills')
check(9, 'ref_files', r9a.get('ref_files', {}))
check(9, 'auto_skills', r9a.get('auto_remediation_skills', []))
check(9, 'total_skills', r9b.get('total', 0))
r9c = api('POST', '/knowledge/run-aggregation')
check(9, 'aggregation', r9c.get('status'))
print(f'    skills={r9b.get("total",0)} auto_skills={len(r9a.get("auto_remediation_skills",[]))} agg_status={r9c.get("status")}')

# ============ STEP 10: Simulate ============
print('\n=== STEP 10: Simulate another scenario ===')
r10 = api('POST', '/incidents/simulate', {'scenario': 'cpu_spike', 'severity': 4})
check(10, 'simulate incident', r10.get('incident', {}).get('incident_id'))
print(f'    new_incident={r10.get("incident",{}).get("incident_id","?")}')

# ============ SUMMARY ============
print('\n' + '=' * 50)
if errors:
    print(f'ISSUES ({len(errors)}):')
    for e in errors:
        print(f'  - {e}')
else:
    print('ALL CHECKS PASSED')
print('=' * 50)

# Cleanup
server.kill()
server.wait()
print('Server stopped.')
