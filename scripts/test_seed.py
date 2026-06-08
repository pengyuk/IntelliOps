"""Quick test that DB seeding works"""
import asyncio
import sys
sys.path.insert(0, 'src')

async def test():
    from backend.db import get_db
    db = get_db("data/test_intelliops.db")
    await db.init()
    await db._seed()
    
    # Check incidents
    incs = await db.list_incidents()
    for inc in incs:
        print(f"  {inc['incident_id']}: [{inc['status']}] {inc['summary'][:60]}")
        tl = await db.list_timeline(inc['incident_id'])
        print(f"    Timeline: {len(tl)} events")
        disc = await db.list_discussion(inc['incident_id'])
        print(f"    Discussion: {len(disc)} messages")
    
    print(f"\nTotal incidents: {len(incs)}")
    await db._get_conn()
    import os
    os.remove("data/test_intelliops.db")
    print("Test OK")

asyncio.run(test())
