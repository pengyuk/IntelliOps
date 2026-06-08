"""Quick test for raw alert ingestion with user's example."""
import sys, os, json, asyncio
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
sys.path.insert(0, os.path.join(PROJECT, 'src'))

db_path = os.path.join(PROJECT, 'data', 'intelliops.db')
if os.path.exists(db_path):
    os.remove(db_path)

from src.backend.app import app, DB
from fastapi.testclient import TestClient

async def init():
    await DB.init()
    await DB._seed()

asyncio.run(init())
client = TestClient(app)

# User's example
r = client.post('/ingest/raw-alert', json={
    "severity": 3,
    "source": "BOCS-DNF",
    "content": "【SA-BPPM】MQ: MAR 31 04:15:44 BQREPXDEPS0 SEV=WAR QPS1 NamedQueue: QR.XMITQ1.QPS1.TO.QMA CURRENT DEPTH: 2197878 (CurrentDepth >= 2000000)."
})
d = r.json()
inc = d.get('incident', {})
deriv = d.get('derivation', {})

print("=" * 50)
print("RAW ALERT INPUT:")
print("  severity=3, source=BOCS-DNF")
print("  content=【SA-BPPM】MQ: ... CURRENT DEPTH: 2197878")
print()
print("PLATFORM DERIVATION:")
print(f"  Keywords: {deriv.get('keywords', [])[:10]}")
print(f"  Matched Systems (KG): {[s['id'] for s in deriv.get('matched_systems', [])]}")
print(f"  Affected Services: {deriv.get('matched_system_ids', [])}")
print(f"  Related Alerts: {inc.get('related_alerts', [])}")
print(f"  Related Changes: {inc.get('related_changes', [])}")
print(f"  Summary: {inc.get('summary', '')}")
print()
print("EXPECTED:")
print("  Affected: ['mq-bocs'] or ['mq-bocs', 'mq-dnf']  (only MQ-related)")
print("  Alerts: ['al-raw-xxx', 'al-bocs-001']  (self + KG alert for mq-bocs)")
print("  Changes: ['chg-dnf-001', 'chg-2603']  (changes affecting mq-bocs)")
print("  NOT expected: svc-cdbc, svc-ipps, svc-rcpsibps")
