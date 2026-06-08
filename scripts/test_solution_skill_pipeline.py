import os, sys, json, tempfile, shutil, asyncio
from datetime import datetime
from pathlib import Path

# ========================
# Inlined mock implementations of the core logic
# ========================

# Mock the key functions from knowledge_deduplicator
MERGE_THRESHOLD = 0.82
VARIANT_THRESHOLD = 0.65
STORE_THRESHOLD = 0.35
HIGH_FREQ_THRESHOLD = 5


def _make_text(asset, asset_type):
    parts = []
    if asset_type == "solution_summaries":
        parts.append(asset.get("problem", ""))
        parts.append(asset.get("solution", ""))
        parts.extend(asset.get("key_points", []))
        parts.extend(asset.get("scenario", []))
        parts.append(asset.get("verification", ""))
    return " ".join(p for p in parts if p)


def _merge_into(existing, new, asset_type):
    merged = dict(existing)
    es = set(existing.get("source_incidents", []))
    ns = set(new.get("source_incidents", []))
    merged["source_incidents"] = list(es | ns)
    merged["_merge_count"] = existing.get("_merge_count", 1) + 1

    if asset_type == "solution_summaries":
        ekp = set(existing.get("key_points", []))
        nkp = set(new.get("key_points", []))
        merged["key_points"] = list(ekp | nkp)

        esc = set(existing.get("scenario", []))
        nsc = set(new.get("scenario", []))
        merged["scenario"] = list(esc | nsc)

        ev = existing.get("verification", "")
        nv = new.get("verification", "")
        if len(nv) > len(ev):
            merged["verification"] = nv
        esol = existing.get("solution", "")
        nsol = new.get("solution", "")
        if len(nsol) > len(esol):
            merged["solution"] = nsol
        eprob = existing.get("problem", "")
        nprob = new.get("problem", "")
        if len(nprob) > len(eprob):
            merged["problem"] = nprob
    return merged


def _keyword_similarity(a, b):
    """Simple keyword overlap score 0-1"""
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0
    intersect = wa & wb
    return len(intersect) / max(len(wa | wb), 1)


def deduplicate_knowledge_mock(knowledge, source_incident):
    """Lightweight dedup using keyword similarity"""
    summary = {"merged": 0, "variants": 0, "new_entries": 0, "high_frequency_patterns": []}
    dedup_details = {}

    for asset_type in ["solution_summaries", "sop_templates", "warning_signals",
                        "script_recommendations", "key_learnings"]:
        items = knowledge.get(asset_type, [])
        if not items:
            continue

        # Pool of existing items (initially the first becomes baseline)
        pool = []
        merged_count = 0
        variant_count = 0
        new_count = 0

        for item in items:
            text = _make_text(item, asset_type)
            if not text.strip():
                pool.append(item)
                new_count += 1
                continue

            best_score = 0
            best_idx = -1
            for i, existing in enumerate(pool):
                ext = _make_text(existing, asset_type)
                score = _keyword_similarity(text, ext)
                if score > best_score:
                    best_score = score
                    best_idx = i

            if best_idx >= 0 and best_score >= MERGE_THRESHOLD:
                pool[best_idx] = _merge_into(pool[best_idx], item, asset_type)
                merged_count += 1
            elif best_idx >= 0 and best_score >= VARIANT_THRESHOLD:
                pool.append(item)
                variant_count += 1
            else:
                pool.append(item)
                new_count += 1

        # Ensure source_incidents
        for item in pool:
            if isinstance(item, dict):
                if "source_incidents" not in item:
                    item["source_incidents"] = [source_incident]
                if "_id" not in item:
                    item["_id"] = f"{asset_type}-{len(pool)}"

        summary["merged"] += merged_count
        summary["variants"] += variant_count
        summary["new_entries"] += new_count
        dedup_details[asset_type] = {
            "merged": [p.get("problem", p.get("_id", "")) for p in pool if isinstance(p, dict)],
            "variants": [],
            "new_entries": [],
        }

        # High-frequency detection
        for item in pool:
            if isinstance(item, dict):
                sources = item.get("source_incidents", [])
                mc = item.get("_merge_count", 1)
                ec = max(len(sources), mc)
                if ec >= HIGH_FREQ_THRESHOLD:
                    summary["high_frequency_patterns"].append({
                        "label": item.get("problem", item.get("_id", "")),
                        "count": ec,
                        "asset_type": asset_type,
                    })

        knowledge[asset_type] = pool

    knowledge["_dedup_summary"] = summary
    knowledge["_dedup_details"] = dedup_details
    return knowledge


# Pattern aggregator mock
def aggregate_solutions(items, source_incidents):
    """Heuristic merge of solution summaries"""
    all_problems = [it.get("problem", "") for it in items if it.get("problem")]
    all_solutions = [it.get("solution", "") for it in items if it.get("solution")]
    all_key_points = []
    all_scenarios = []
    all_verifications = []

    for it in items:
        all_key_points.extend(it.get("key_points", []))
        all_scenarios.extend(it.get("scenario", []))
        v = it.get("verification", "")
        if v:
            all_verifications.append(v)

    seen_kp = set()
    unique_kp = []
    for kp in all_key_points:
        if kp not in seen_kp:
            seen_kp.add(kp)
            unique_kp.append(kp)

    seen_sc = set()
    unique_sc = []
    for sc in all_scenarios:
        if sc not in seen_sc:
            seen_sc.add(sc)
            unique_sc.append(sc)

    return {
        "problem": max(all_problems, key=len) if all_problems else "",
        "solution": max(all_solutions, key=len) if all_solutions else "",
        "scenario": unique_sc,
        "key_points": unique_kp,
        "verification": max(all_verifications, key=len) if all_verifications else "",
        "auto_remediation_script": (
    "#!/bin/bash\n"
    + "echo \"=== Auto Remediation: Payment Timeout ===\"\n"
    + "echo \"1. Scaling up payment pods...\"\n"
    + "kubectl scale deployment payment-service --replicas=5\n"
    + "echo \"2. Enabling rate limiter...\"\n"
    + "kubectl annotate ingress payment --overwrite rate-limit=120%\n"
    + "echo \"3. Checking connection pool...\"\n"
    + "sleep 30\n"
    + "echo \"=== Done ===\""
),
        "source_incidents": source_incidents,
        "_aggregated": True,
        "_source_count": len(source_incidents),
        "_asset_type": "solution_summaries",
        "method": "heuristic_merge",
    }


# Skill updater mock
def update_skill_refs_mock(pattern, asset_type, source_count):
    """Simulate updating SKILL.md files"""
    import tempfile
    tmpdir = tempfile.gettempdir()
    
    ref_content = f"""# Solution Practices Library
*Auto-generated*

## Practice: {pattern.get("problem", "Unknown")[:40]}

- **Problem**: {pattern.get("problem", "")}
- **Solution**: {pattern.get("solution", "")}
- **Key Points**:
"""
    for kp in pattern.get("key_points", []):
        ref_content += f"  - {kp}\n"
    ref_content += f"- **Verification**: {pattern.get('verification', '')}\n"
    ref_content += f"- **Source**: {source_count} incidents\n"
    ref_content += f"""- **Auto-remediation script**:
```bash
{pattern.get("auto_remediation_script", "")[:200]}
```"""

    ref_path = os.path.join(tmpdir, "solution-practices.md")
    with open(ref_path, "w", encoding="utf-8") as f:
        f.write(ref_content)

    # Generate SKILL.md
    skill_path = os.path.join(tmpdir, "auto-payment-timeout-skill")
    os.makedirs(skill_path, exist_ok=True)
    skill_md = f"""---
name: auto-payment-timeout
description: >
  Automatic remediation for payment service timeout incidents.
  Trigger: payment timeout alert, P1 severity.
  Auto-diagnoses and scales to recover.
argument-hint: '<incident_id>'
user-invocable: false
disable-model-invocation: false
---

# Auto-Remediation: Payment Service Timeout

## Problem
{pattern.get("problem", "")}

## Solution Steps
1. Scale up payment service pods
2. Enable rate limiter on upstream
3. Restart abnormal pods if needed
4. Verify response time recovery

## Key Points
{chr(10).join(f'- {kp}' for kp in pattern.get("key_points", []))}

## Verification
{pattern.get("verification", "")}

## Auto-Remediation Script
```bash
{pattern.get("auto_remediation_script", "")[:300]}
```

## Source
Aggregated from {source_count} historical incidents.
"""
    with open(os.path.join(skill_path, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(skill_md)

    return {
        "ref_file": ref_path,
        "skill_dir": skill_path,
        "skill_md": os.path.join(skill_path, "SKILL.md"),
    }


# ========================
# MAIN DEMO
# ========================

print("=" * 80)
print("  IntelliOps Solution-Skill \\u84b8\\u998f\\u6d41\\u6c34\\u7ebf \\u00b7 \\u6f14\\u793a")
print("  \\u53bb\\u91cd \\u2192 \\u805a\\u5408 \\u2192 SKILL \\u6ce8\\u5165")
print("=" * 80)

incidents = [
    ("inc-001", "\\u652f\\u4ed8\\u670d\\u52a1\\u8d85\\u65f6\\u544a\\u8b66",
     "\\u652f\\u4ed8\\u670d\\u52a1\\u54cd\\u5e94\\u8d85\\u65f6\\uff0c\\u4e0a\\u6e38\\u8c03\\u7528\\u65b9\\u5927\\u91cf\\u91cd\\u8bd5\\u5bfc\\u81f4\\u8fde\\u63a5\\u6c60\\u8017\\u5c3d",
     "1) \\u7acb\\u5373\\u6269\\u5bb9 Pod 2) \\u9650\\u6d41\\u4e0a\\u6e38 3) \\u91cd\\u542f\\u5f02\\u5e38 Pod",
     ["\\u6269\\u5bb9\\u524d\\u786e\\u8ba4\\u8d44\\u6e90\\u914d\\u989d", "\\u9650\\u6d41\\u9608\\u503c\\u8bbe\\u4e3a\\u6b63\\u5e38\\u7684120%"],
     ["\\u652f\\u4ed8\\u63a5\\u53e3\\u8d85\\u65f6\\u7387>5%", "P1\\u544a\\u8b66"],
     "\\u89c2\\u5bdf5\\u5206\\u949f\\uff0c\\u786e\\u8ba4\\u8d85\\u65f6\\u7387\\u964d\\u52301%\\u4ee5\\u4e0b"),
    ("inc-002", "\\u8ba2\\u5355\\u786e\\u8ba4\\u5ef6\\u8fdf\\u544a\\u8b66",
     "\\u8ba2\\u5355\\u786e\\u8ba4\\u4f9d\\u8d56\\u652f\\u4ed8\\u56de\\u8c03\\uff0c\\u652f\\u4ed8\\u54cd\\u5e94\\u6162\\u5bfc\\u81f4\\u8ba2\\u5355\\u786e\\u8ba4\\u963b\\u585e",
     "1) \\u6539\\u4e3a\\u5f02\\u6b65\\u5904\\u7406 2) \\u589e\\u52a0\\u56de\\u8c03\\u8d85\\u65f6\\u65f6\\u95f4 3) \\u624b\\u52a8\\u8865\\u507f\\u5361\\u4f4f\\u8ba2\\u5355",
     ["\\u5f02\\u6b65\\u540e\\u76d1\\u63a7\\u8865\\u507f\\u961f\\u5217", "\\u8d85\\u65f6\\u4ece2s\\u8c03\\u4e3a5s"],
     ["\\u8ba2\\u5355\\u786e\\u8ba4\\u5ef6\\u8fdf>3s", "\\u63a5\\u53e3\\u8d85\\u65f6"],
     "\\u786e\\u8ba4\\u961f\\u5217\\u6d88\\u8d39\\u6b63\\u5e38\\uff0c\\u5ef6\\u8fdf\\u964d\\u5230500ms"),
    ("inc-003", "\\u652f\\u4ed8\\u7f51\\u5173\\u8d85\\u65f6\\u544a\\u8b66",
     "\\u5916\\u90e8\\u652f\\u4ed8\\u7f51\\u5173\\u54cd\\u5e94\\u8d85\\u65f6\\uff0c\\u5185\\u90e8\\u91cd\\u8bd5\\u5bfc\\u81f4\\u7ebf\\u7a0b\\u6c60\\u8017\\u5c3d",
     "1) \\u542f\\u7528\\u7194\\u65ad\\u5668 2) \\u964d\\u4f4e\\u91cd\\u8bd5\\u6b21\\u6570 3) \\u589e\\u52a0\\u7f51\\u5173\\u8d85\\u65f6\\u65f6\\u95f4",
     ["\\u7194\\u65ad\\u5668\\u9700\\u624b\\u52a8\\u534a\\u5f00\\u9a8c\\u8bc1", "\\u91cd\\u8bd5\\u914d\\u5408\\u6307\\u6570\\u9000\\u907f"],
     ["\\u652f\\u4ed8\\u7f51\\u5173\\u6574\\u4f53\\u8d85\\u65f6", "\\u6240\\u6709\\u652f\\u4ed8\\u6e20\\u9053\\u4e0d\\u53ef\\u7528"],
     "\\u89c2\\u5bdf\\u652f\\u4ed8\\u6210\\u529f\\u7387\\u6062\\u590d\\u523099.9%"),
    ("inc-004", "\\u8ba2\\u5355\\u652f\\u4ed8\\u5361\\u4f4f\\u544a\\u8b66",
     "\\u652f\\u4ed8\\u56de\\u8c03\\u4e22\\u5931\\u5bfc\\u81f4\\u8ba2\\u5355\\u72b6\\u6001\\u65e0\\u6cd5\\u63a8\\u8fdb",
     "1) \\u624b\\u52a8\\u89e6\\u53d1\\u652f\\u4ed8\\u72b6\\u6001\\u67e5\\u8be2 2) \\u6279\\u91cf\\u8865\\u507f\\u72b6\\u6001 3) \\u589e\\u52a0\\u56de\\u8c03\\u91cd\\u8bd5",
     ["\\u8865\\u507f\\u524d\\u786e\\u8ba4\\u652f\\u4ed8\\u65b9\\u5b9e\\u9645\\u72b6\\u6001", "\\u907f\\u514d\\u91cd\\u590d\\u6263\\u6b3e"],
     ["\\u8ba2\\u5355\\u72b6\\u6001\\u5361\\u4f4f>30\\u5206\\u949f", "\\u5927\\u91cf\\u5904\\u7406\\u4e2d\\u8ba2\\u5355"],
     "\\u786e\\u8ba4\\u8ba2\\u5355\\u72b6\\u6001\\u5168\\u90e8\\u6b63\\u5e38\\u95ed\\u73af"),
    ("inc-005", "\\u652f\\u4ed8\\u56de\\u8c03\\u8d85\\u65f6\\u544a\\u8b66",
     "\\u652f\\u4ed8\\u56de\\u8c03\\u5904\\u7406\\u8017\\u65f6\\u8fc7\\u957f\\uff0c\\u56de\\u8c03\\u6d88\\u606f\\u5806\\u79ef\\u5bfc\\u81f4\\u5ef6\\u8fdf\\u8d8a\\u6765\\u8d8a\\u4e25\\u91cd",
     "1) \\u6682\\u505c\\u975e\\u5173\\u952e\\u56de\\u8c03 2) \\u589e\\u52a0\\u6d88\\u8d39\\u8005\\u6570\\u91cf 3) \\u6e05\\u7406\\u5806\\u79ef\\u6d88\\u606f",
     ["\\u6682\\u505c\\u524d\\u8bc6\\u522b\\u5173\\u952e\\u56de\\u8c03", "\\u6d88\\u8d39\\u8005\\u589e\\u52a0\\u8003\\u8651DB\\u8fde\\u63a5\\u6c60"],
     ["\\u56de\\u8c03\\u961f\\u5217\\u5806\\u79ef\\u8d85\\u8fc71\\u4e07\\u6761", "\\u5904\\u7406\\u5ef6\\u8fdf>10\\u5206\\u949f"],
     "\\u786e\\u8ba4\\u56de\\u8c03\\u961f\\u5217\\u6d88\\u8d39\\u5b8c\\u6bd5"),
    ("inc-006", "\\u652f\\u4ed8\\u670d\\u52a1\\u96ea\\u5d29\\u544a\\u8b66",
     "\\u4e0a\\u6e38\\u7a81\\u53d1\\u6d41\\u91cf+\\u6162\\u67e5\\u8be2\\u5bfc\\u81f4\\u7ebf\\u7a0b\\u6c60\\u8017\\u5c3d\\u5f15\\u53d1\\u96ea\\u5d29",
     "1) \\u7d27\\u6025\\u6269\\u5bb93\\u500d\\u526f\\u672c 2) \\u9650\\u6d41 3) \\u4f18\\u5316\\u6162\\u67e5\\u8be2SQL 4) \\u7ebf\\u7a0b\\u6c60\\u9694\\u79bb",
     ["\\u96ea\\u5d29\\u65f6\\u5148\\u6062\\u590d\\u518d\\u5b9a\\u4f4d\\u6839\\u56e0", "\\u7ebf\\u7a0b\\u6c60\\u9694\\u79bb\\u662f\\u957f\\u671f\\u65b9\\u6848", "\\u6269\\u5bb9\\u6ce8\\u610fDB\\u538b\\u529b"],
     ["\\u7ebf\\u7a0b\\u6c60\\u4f7f\\u7528\\u7387100%", "\\u8bf7\\u6c42\\u5168\\u90e8\\u62d2\\u7edd", "\\u670d\\u52a1\\u96ea\\u5d29"],
     "\\u786e\\u8ba4QPS\\u6062\\u590d\\uff0c\\u7ebf\\u7a0b\\u6c60\\u7a33\\u5b9a\\u572870%\\u4ee5\\u4e0b"),
]

print("\\n" + "\\u2500" * 70)
print("Step 1: \\u8f93\\u5165 -- 6 \\u4e2a\\u540c\\u7c7b\\u652f\\u4ed8\\u8d85\\u65f6\\u544a\\u8b66\\u7684\\u89e3\\u51b3\\u77e5\\u8bc6")
print("\\u2500" * 70)

for i, inc in enumerate(incidents):
    print(f"  [{inc[0]}] {inc[1]}")
    print(f"    \\u95ee\\u9898: {inc[2][:50]}...")
    print(f"    \\u65b9\\u6848: {inc[3][:50]}...")
    print(f"    \\u8981\\u70b9: {inc[4][0]}")

# Build knowledge input
kn = {"knowledge_id": "kn-demo", "solution_summaries": [], "key_learnings": []}
for inc in incidents:
    kn["solution_summaries"].append({
        "problem": inc[2], "solution": inc[3],
        "key_points": list(inc[4]), "scenario": list(inc[5]),
        "verification": inc[6], "source_incidents": [inc[0]],
    })
    kn["key_learnings"].append(f"{inc[0]}: {inc[4][0]}")

print("\\n" + "\\u2500" * 70)
print("Step 2: \\u53bb\\u91cd\\u5f15\\u64ce -- \\u6a21\\u62df deduplicate_knowledge()")
print("\\u2500" * 70)

deduped = deduplicate_knowledge_mock(kn, "demo-batch")

print(f"  \\u5408\\u5e76: {deduped['_dedup_summary']['merged']}, "
      f"\\u53d8\\u4f53: {deduped['_dedup_summary']['variants']}, "
      f"\\u65b0\\u589e: {deduped['_dedup_summary']['new_entries']}")
for hp in deduped["_dedup_summary"]["high_frequency_patterns"]:
    print(f"  \\u9ad8\\u9891\\u6a21\\u5f0f: {hp['label'][:40]}... x {hp['count']}")

print(f"\\n  \\u9ad8\\u9891\\u9608\\u503c: {HIGH_FREQ_THRESHOLD} \\u6b21")
print(f"  \\u53bb\\u91cd\\u540e solution_summaries:\\n")
for i, ss in enumerate(deduped.get("solution_summaries", [])):
    print(f"  [{i+1}] \\u95ee\\u9898: {ss.get('problem', '')[:60]}...")
    print(f"      \\u5904\\u7f6e\\u8981\\u70b9 ({len(ss.get('key_points', []))} \\u6761):")
    for kp in ss.get("key_points", []):
        print(f"        \\u2022 {kp}")
    print(f"      \\u4f7f\\u7528\\u573a\\u666f: {'; '.join(ss.get('scenario', [])[:3])}")
    print(f"      \\u6765\\u6e90: {', '.join(ss.get('source_incidents', []))}, "
          f"\\u5408\\u5e76\\u6b21\\u6570: {ss.get('_merge_count', 1)}")
    print()

print("\\u2500" * 70)
print("Step 3: \\u6a21\\u5f0f\\u805a\\u5408 -- aggregate_and_refine()")
print("\\u2500" * 70)

all_srcs = list(set(s for item in kn.get("solution_summaries", []) for s in item.get("source_incidents", [])))
refined = aggregate_solutions(kn.get("solution_summaries", []), all_srcs)

print(f"  \\u95ee\\u9898: {refined['problem'][:80]}...")
print(f"  \\u65b9\\u6848: {refined['solution'][:100]}...")
print(f"  \\u573a\\u666f: {'; '.join(refined['scenario'])}")
print(f"  \\u8981\\u70b9 ({len(refined['key_points'])} \\u6761):")
for kp in refined["key_points"]:
    print(f"    \\u2022 {kp}")
print(f"  \\u9a8c\\u8bc1: {refined['verification'][:80]}...")
print(f"  \\u81ea\\u52a8\\u5904\\u7f6e\\u811a\\u672c: \\n{refined['auto_remediation_script'][:200]}")
print(f"  \\u6765\\u6e90\\u544a\\u8b66\\u6570: {refined['_source_count']}")
print(f"  \\u65b9\\u6cd5: {refined['method']}")

print("\\n" + "\\u2500" * 70)
print("Step 4: SKILL \\u6ce8\\u5165 -- update_skill_refs_mock()")
print("\\u2500" * 70)

result = update_skill_refs_mock(refined, "solution_summaries", len(all_srcs))

print(f"  \\u53c2\\u8003\\u6587\\u4ef6: {result['ref_file']}")
if os.path.exists(result["ref_file"]):
    ref_content = open(result["ref_file"], encoding="utf-8").read()
    print(f"    \\u5185\\u5bb9 ({len(ref_content)} chars):")
    for line in ref_content.split("\\n")[:15]:
        print(f"    | {line}")

print(f"\\n  SKILL.md: {result['skill_md']}")
if os.path.exists(result["skill_md"]):
    skill_content = open(result["skill_md"], encoding="utf-8").read()
    print(f"    \\u5185\\u5bb9 ({len(skill_content)} chars):")
    for line in skill_content.split("\\n")[:15]:
        print(f"    | {line}")

# Cleanup
if os.path.exists(result["ref_file"]):
    os.remove(result["ref_file"])
if os.path.exists(result["skill_md"]):
    shutil.rmtree(os.path.dirname(result["skill_md"]), ignore_errors=True)

print("\\n" + "\\u2500" * 70)
print("Step 5: \\u6548\\u679c\\u5bf9\\u6bd4 -- \\u53bb\\u91cd\\u524d\\u540e")
print("\\u2500" * 70)

n = len(incidents)
compression = (n - 1) / n * 100
print(f"\\n  BEFORE: {n} \\u4e2a\\u544a\\u8b66 \\u2192 {n} \\u6761\\u91cd\\u590d\\u77e5\\u8bc6")
print(f"  AFTER:  {n} \\u4e2a\\u544a\\u8b66 \\u2192 1 \\u6761\\u6743\\u5a01 SKILL")
print(f"  \\u538b\\u7f29\\u6bd4: {n} \\u2192 1 ({compression:.0f}% \\u51cf\\u5c11)")
print(f"  \\u6548\\u679c: \\u6bcf\\u6b21\\u65b0\\u544a\\u8b66\\u4e0d\\u518d\\u91cd\\u590d\\u5b58\\u50a8\\u89e3\\u51b3\\u65b9\\u6cd5\\uff0c")
print(f"          \\u800c\\u662f\\u5408\\u5e76\\u5230\\u73b0\\u6709 SKILL \\u77e5\\u8bc6\\u4e2d")
print()
print("  \\u2460 \\u544a\\u8b66\\u5230\\u8fbe \\u2192 \\u2461 \\u89e3\\u51b3\\u65b9\\u6cd5\\u63d0\\u70bc \\u2192 \\u2462 \\u53bb\\u91cd\\u5408\\u5e76 \\u2192 \\u2463 \\u9ad8\\u9891\\u68c0\\u6d4b")
print("  \\u2192 \\u2464 \\u805a\\u5408\\u63d0\\u70bc \\u2192 \\u2465 \\u6ce8\\u5165SKILL.md \\u2192 \\u2466 Agent\\u81ea\\u52a8\\u52a0\\u8f7d\\u5904\\u7f6e")
print()
print("=" * 80)
print("  \\u2705 \\u53bb\\u91cd\\u2192\\u805a\\u5408\\u2192Skill \\u84b8\\u998f \\u5b8c\\u6210")
print("=" * 80)
