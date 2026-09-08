import json
import sys
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')

def analyze():
    with open("scratch/extracted_facts_dump.json", "r", encoding="utf-8") as f:
        facts = json.load(f)

    with open("scratch/rejected_extractions_dump.json", "r", encoding="utf-8") as f:
        rejected = json.load(f)

    with open("scratch/relationships_dump.json", "r", encoding="utf-8") as f:
        rels = json.load(f)

    print("=== SAMPLE EXTRACTED FACTS (First 25) ===")
    for idx, fact in enumerate(facts[:25]):
        print(f"[{idx+1}] ID:{fact['id']} | Entity: '{fact['entity']}' | Metric: '{fact['metric']}' | Value: '{fact['value']}' (Norm: {fact['normalized_value']} {fact['normalized_unit']}) | Period: '{fact['period']}' | Quote: '{fact['raw_quote'][:60]}...'")

    print("\n=== METRIC FREQUENCY (Top 20) ===")
    metric_counts = Counter(f["metric"] for f in facts)
    for m, c in metric_counts.most_common(20):
        print(f"  - '{m}': {c} times")

    print("\n=== SAMPLE REJECTED EXTRACTIONS (First 15) ===")
    for idx, rj in enumerate(rejected[:15]):
        print(f"[{idx+1}] Failure: {rj['failure_type']} | Text: '{rj['candidate_text']}' | Reason: {rj['rejection_reason']}")

    print("\n=== SAMPLE RELATIONSHIPS (First 25) ===")
    for idx, r in enumerate(rels[:25]):
        fa = next((f for f in facts if f["id"] == r["fact_id_a"]), None)
        fb = next((f for f in facts if f["id"] == r["fact_id_b"]), None)
        fa_str = f"'{fa['metric']}': {fa['value']} ({fa['period']})" if fa else f"Fact #{r['fact_id_a']}"
        fb_str = f"'{fb['metric']}': {fb['value']} ({fb['period']})" if fb else f"Fact #{r['fact_id_b']}"
        print(f"[{idx+1}] Rel: {r['relationship_type']} ({r['reconciliation_type']}) | A: {fa_str} <--> B: {fb_str}")
        print(f"     Reasoning: {r['reasoning']}")

if __name__ == "__main__":
    analyze()
