import sys
sys.path.insert(0, '.')
import sqlite3
import json
from app.main import list_all_facts
from app.matching import calculate_comparability_score, find_candidate_pairs, canonicalize_metric

facts = [f.model_dump() for f in list_all_facts()]
print(f"Total facts in DB: {len(facts)}")

print("\n--- Facts with 'express' or 'parcel' or 'female' or 'workforce' ---")
for f in facts:
    metric = f.get("metric") or ""
    val = f.get("value") or ""
    if any(kw in metric.lower() or kw in val.lower() for kw in ["express", "parcel", "female", "workforce", "shipment"]):
        print(f"ID: {f['id']} | Doc: {f['source_document']} | Metric: '{f['metric']}' | Canon: '{canonicalize_metric(f['metric'])}' | Value: '{f['value']}' | Period: '{f['period']}' | Unit: '{f['unit']}'")

print("\n--- Candidate pairs generated ---")
candidates = find_candidate_pairs(facts, max_candidates=100)
print(f"Candidate pairs generated count: {len(candidates)}")

for f_a, f_b, score, passed in candidates[:20]:
    print(f"Pair ({f_a['id']} vs {f_b['id']}): Metric A: '{f_a['metric']}' ({f_a['value']}) vs Metric B: '{f_b['metric']}' ({f_b['value']}) | Score: {score}")
