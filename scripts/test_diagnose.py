"""Quick diagnose test."""
import urllib.request
import json
import sys

# Get first incident
req = urllib.request.Request('http://localhost:8000/incidents')
data = json.loads(urllib.request.urlopen(req, timeout=10).read())
inc_id = data['incidents'][0]['incident_id']
print(f'Incident: {inc_id}')

# Diagnose
req2 = urllib.request.Request(
    'http://localhost:8000/copilot/diagnose',
    data=json.dumps({'incident_id': inc_id, 'user_id': 'ui-user'}).encode(),
    method='POST'
)
req2.add_header('Content-Type', 'application/json')
print('Calling /copilot/diagnose ...')
resp = urllib.request.urlopen(req2, timeout=120)
result = json.loads(resp.read())

print(f"diagnosis_id: {result.get('diagnosis_id')}")
print(f"active_skills: {result.get('active_skills')}")
print(f"primary_skill: {result.get('primary_skill')}")
print(f"skill_suggestions: {result.get('skill_suggestions')}")
print(f"confidence_summary: {result.get('confidence_summary')}")
print("OK - Diagnose works with Skill context!")
