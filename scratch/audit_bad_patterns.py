import json
from collections import Counter

def audit():
    with open("scratch/extracted_facts_dump.json", "r", encoding="utf-8") as f:
        facts = json.load(f)

    print(f"Total Facts: {len(facts)}")

    unit_metrics = []
    short_metrics = []
    no_num_facts = []

    for f in facts:
        m = (f.get("metric") or "").strip().lower()
        if m in {"million", "crore", "lakh", "billion", "thousand", "mn", "bn", "cr", "particulars", "table unit header", "general metric"}:
            unit_metrics.append(f)
        elif len(m) < 4:
            short_metrics.append(f)
        if f.get("numeric_value") is None:
            no_num_facts.append(f)

    print(f"Facts with bare unit/header as metric name: {len(unit_metrics)} ({len(unit_metrics)/len(facts)*100:.1f}%)")
    print(f"Facts with very short metric names (<4 chars): {len(short_metrics)}")
    print(f"Non-numeric facts: {len(no_num_facts)}")

    print("\n--- Top 30 Bad Metric Names ---")
    bad_counts = Counter((f.get("metric") or "").strip() for f in unit_metrics + short_metrics)
    for m, c in bad_counts.most_common(30):
        print(f"  - '{m}': {c} occurrences")

if __name__ == "__main__":
    audit()
