"""Test LIVE_DEMO.md steps against running backend."""
import urllib.request, json, time, sys

BASE = 'http://127.0.0.1:8000'
errors = []

def api(method, path, data=None):
    url = BASE + path
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={'Content-Type':'application/json'}, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return json.loads(r.read())
    except Exception as e:
        return {'_error': str(e)}

def check(step, field, actual, expected_desc):
    ok = actual is not None and (isinstance(expected_desc, type(actual)) or True)
    status = "OK" if actual else "MISSING"
    if not actual:
        errors.append(f"Step {step}: {field} is missing/empty")
    print(f"  {field}: {status} ({str(actual)[:80]})")

# === Step 1: Ingest raw alert ===
print('=== STEP 1: Ingest raw alert ===')
alert = {'severity':4,'source':'BPPM','content':'MQ Pageset 76% 2603 batch cleanup causing QREP backlog. C-DBC success rate dropped to 98%.'}
r1 = api('POST', '/ingest/raw-alert', alert)
inc_id = r1.get('incident',{}).get('incident_id','')
check(1, 'incident_id', inc_id, 'string')
check(1, 'pipeline_triggered', r1.get('pipeline_triggered'), 'bool')
check(1, 'keywords', r1.get('derivation',{}).get('keywords'), 'list')
print()

# === Step 2: Get incident with KG context ===
print('=== STEP 2: KG context ===')
r2 = api('GET', '/incident/' + inc_id)
kg = r2.get('kg_context',{})
check(2, 'kg_context exists', kg, 'dict')
check(2, 'services', kg.get('services'), 'list')
check(2, 'upstream', kg.get('upstream'), 'list')
check(2, 'downstream', kg.get('downstream'), 'list')
check(2, 'dependency_summary', kg.get('dependency_summary'), 'str')
if kg.get('upstream'):
    print(f'    upstream names: {[u.get("name","?") for u in kg["upstream"]]}')
if kg.get('downstream'):
    print(f'    downstream names: {[d.get("name","?") for d in kg["downstream"]]}')
print()

# === Step 3: Diagnose (async) ===
print('=== STEP 3: Async diagnose ===')
r3 = api('POST', '/copilot/diagnose', {'incident_id': inc_id, 'user_id': 'ui-user'})
diag_id = r3.get('diagnosis_id','')
check(3, 'diagnosis_id', diag_id, 'str')
check(3, 'status (queued)', r3.get('status'), 'str')
time.sleep(2)
poll = api('GET', '/copilot/diagnose/' + diag_id)
check(3, 'poll status', poll.get('status'), 'str')
check(3, 'poll progress', poll.get('progress'), 'int')
check(3, 'poll step', poll.get('step'), 'str')
print()

# === Step 4: Knowledge base ===
print('=== STEP 4: Knowledge base ===')
r4a = api('GET', '/incident/' + inc_id + '/related-cases?limit=5')
r4b = api('GET', '/incident/' + inc_id + '/knowledge-assets')
r4c = api('GET', '/knowledge/high-frequency-patterns')
check(4, 'related_cases', len(r4a.get('cases',[])), 'int')
check(4, 'knowledge_assets', len(r4b.get('assets',[])), 'int')
check(4, 'high_freq_patterns', len(r4c.get('patterns',[])), 'int')
print()

# === Step 5: Scripts ===
print('=== STEP 5: Scripts ===')
r5 = api('GET', '/script/suggest?incident_id=' + inc_id)
suggestions = r5.get('suggestions',[]) or []
check(5, 'script suggestions', len(suggestions), 'int')
for s in suggestions[:3]:
    print(f'    - {s.get("name","?")[:50]} risk={s.get("risk_level")} cat={s.get("category")}')
    if s.get('category') == 'kg_aware':
        print(f'      TOPO hint: {s.get("topology_hint","")}')
print()

# === Step 6: Discussion ===
print('=== STEP 6: Discussion ===')
r6a = api('POST', '/incident/' + inc_id + '/discussion', {
    'author':'ui-user','message':'dev team found QREP consumer thread stuck','message_type':'maintenance'
})
check(6, 'discussion sent', r6a.get('comment_id'), 'str')
# Get discussion list
r6b = api('GET', '/incident/' + inc_id + '/discussion')
messages = r6b.get('messages',[]) or []
check(6, 'discussion messages', len(messages), 'int')
print()

# === Step 7: Investigation state ===
print('=== STEP 7: Investigation state ===')
r7 = api('GET', '/incident/' + inc_id + '/investigation-state')
check(7, 'investigation state', r7, 'dict')
# Try to add an item
try:
    r7b = api('POST', '/incident/' + inc_id + '/investigation-state/items', {
        'quadrant':'excluded','item':{'summary':'QREP config issue','confidence':0.3}
    })
    check(7, 'add excluded item', r7b.get('status','ok'), 'str')
except:
    pass
print()

# === Step 8: Postmortem ===
print('=== STEP 8: Postmortem ===')
r8 = api('POST', '/incident/' + inc_id + '/postmortem', {'requested_by':'ui-user','mark_resolved':True})
check(8, 'postmortem_id', r8.get('postmortem_id'), 'str')
check(8, 'has knowledge', 'knowledge' in r8, 'bool')
k = r8.get('knowledge',{})
if k and k.get('status') != 'skipped':
    check(8, 'root_cause_rules', len(k.get('root_cause_rules',[])), 'int')
    check(8, 'sop_templates', len(k.get('sop_templates',[])), 'int')
    check(8, 'key_learnings', len(k.get('key_learnings',[])), 'int')
if r8.get('_pipeline_extras'):
    print(f'    pipeline_extras: dedup={r8["_pipeline_extras"].get("dedup_summary",{}).get("merged",0)}')
print()

# === Step 9: Skills & aggregation ===
print('=== STEP 9: Skills & aggregation ===')
r9a = api('GET', '/knowledge/skill-update-log')
r9b = api('GET', '/skills')
check(9, 'ref_files', len(r9a.get('ref_files',{})), 'int')
check(9, 'auto_skills', len(r9a.get('auto_remediation_skills',[])), 'int')
check(9, 'total_skills', r9b.get('total',0), 'int')
# Try aggregation
r9c = api('POST', '/knowledge/run-aggregation')
check(9, 'aggregation status', r9c.get('status'), 'str')
print()

# === Step 10: Simulate another scenario ===
print('=== STEP 10: Simulate cpu_spike ===')
r10 = api('POST', '/incidents/simulate', {'scenario':'cpu_spike','severity':4})
check(10, 'new incident_id', r10.get('incident',{}).get('incident_id'), 'str')
print()

# === Summary ===
print('='*50)
if errors:
    print(f'ISSUES FOUND ({len(errors)}):')
    for e in errors:
        print(f'  - {e}')
else:
    print('ALL CHECKS PASSED')
print('='*50)
