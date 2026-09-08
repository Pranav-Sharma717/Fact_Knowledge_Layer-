import sys
sys.path.insert(0, '.')
from app.main import list_all_facts
from app.matching import calculate_comparability_score, judge_relationship, find_candidate_pairs

facts = [f.model_dump() for f in list_all_facts()]

f1 = next(f for f in facts if f["id"] == 1)
f132 = next(f for f in facts if f["id"] == 132)

print("Fact 1:", f1)
print("Fact 132:", f132)

score, passed, failed = calculate_comparability_score(f1, f132)
print(f"\nComparability score: {score}")
print("Passed gates:", passed)
print("Failed gates:", failed)

judge_res = judge_relationship(f1, f132)
print("\nJudge relationship result:", judge_res)

print("\n--- Why candidate pairs loop didn't include Fact 1 & 132 ---")
all_pairs = find_candidate_pairs(facts, max_candidates=500)
pair_ids = [(p[0]['id'], p[1]['id']) for p in all_pairs]
print("Is (1, 132) in candidate pairs?", (1, 132) in pair_ids or (132, 1) in pair_ids)
if (1, 132) in pair_ids:
    idx = [i for i, p in enumerate(all_pairs) if (p[0]['id'], p[1]['id']) == (1, 132) or (p[0]['id'], p[1]['id']) == (132, 1)][0]
    print(f"Rank of (1, 132) in sorted candidate pairs: {idx + 1} out of {len(all_pairs)}")
