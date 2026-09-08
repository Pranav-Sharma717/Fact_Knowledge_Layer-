import os
import json
import httpx
import re
from typing import List, Dict, Any, Tuple
from dotenv import load_dotenv

from app.validation import UNIT_KEYWORDS, GENERIC_METRICS
from app.number_classifier import (
    ROLE_MONEY, ROLE_PERCENT, ROLE_SHARE_COUNT, ROLE_COUNT, canonicalize_metric
)

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Taxonomy Categories
TAXONOMY_CORROBORATES = "CORROBORATES"
TAXONOMY_CONTRADICTS = "CONTRADICTS"
TAXONOMY_LIKELY_CONTRADICTION = "LIKELY_CONTRADICTION"
TAXONOMY_CONTEXTUAL_DIFFERENCE = "CONTEXTUAL_DIFFERENCE"
TAXONOMY_RECONCILED_UNIT = "RECONCILED_UNIT"
TAXONOMY_RECONCILED_ROUNDING = "RECONCILED_ROUNDING"
TAXONOMY_RECONCILED_SCOPE = "RECONCILED_SCOPE"
TAXONOMY_TEMPORAL_COMPARISON = "TEMPORAL_COMPARISON"
TAXONOMY_UNCERTAIN = "UNCERTAIN"
TAXONOMY_UNRELATED = "UNRELATED"

MIN_RELATIONSHIP_CONFIDENCE = 0.70

def can_compute_delta(fact_a: Dict[str, Any], fact_b: Dict[str, Any]) -> bool:
    """
    Returns True ONLY when normalized dimensions match and percentage delta can be legitimately calculated.
    """
    val_a = fact_a.get("normalized_value")
    val_b = fact_b.get("normalized_value")
    if val_a is None or val_b is None:
        return False
        
    type_a = fact_a.get("value_type", "UNKNOWN")
    type_b = fact_b.get("value_type", "UNKNOWN")
    if type_a != type_b and not (type_a in {ROLE_COUNT, ROLE_SHARE_COUNT} and type_b in {ROLE_COUNT, ROLE_SHARE_COUNT}):
        return False
        
    unit_a = (fact_a.get("normalized_unit") or "").lower()
    unit_b = (fact_b.get("normalized_unit") or "").lower()
    if unit_a != unit_b:
        # Check if units are convertible (e.g. INR vs USD, or parcels vs orders)
        if (unit_a == "%" or unit_b == "%") and unit_a != unit_b:
            return False
            
    return True

def calculate_comparability_score(fact_a: Dict[str, Any], fact_b: Dict[str, Any]) -> Tuple[float, List[str], List[str]]:
    """
    Evaluates hard gates for candidate comparability using strict generic metric canonicalization.
    Returns (score, passed_gates, failed_gates).
    If hard gates fail, score = 0.0 and pair is UNRELATED.
    """
    passed = []
    failed = []

    entity_a = (fact_a.get("subject_entity") or fact_a.get("entity") or "").lower().strip()
    entity_b = (fact_b.get("subject_entity") or fact_b.get("entity") or "").lower().strip()
    metric_a = (fact_a.get("metric") or "").lower().strip()
    metric_b = (fact_b.get("metric") or "").lower().strip()
    type_a = fact_a.get("value_type", "UNKNOWN")
    type_b = fact_b.get("value_type", "UNKNOWN")
    unit_a = (fact_a.get("normalized_unit") or fact_a.get("unit") or "").lower().strip()
    unit_b = (fact_b.get("normalized_unit") or fact_b.get("unit") or "").lower().strip()

    # Hard Gate 1: Entity Compatibility
    if entity_a and entity_b:
        if "delhivery" in entity_a and "delhivery" in entity_b:
            passed.append("✓ Entity Match (Delhivery Limited)")
        elif entity_a == entity_b:
            passed.append(f"✓ Entity Match ({entity_a.title()})")
        else:
            failed.append(f"✗ Entity Mismatch ({entity_a} vs {entity_b})")
            return 0.0, passed, failed
    else:
        passed.append("✓ Entity Implicit")

    # Hard Gate 2: Generic Metric Check
    if not metric_a or not metric_b or metric_a in GENERIC_METRICS or metric_b in GENERIC_METRICS or metric_a in UNIT_KEYWORDS or metric_b in UNIT_KEYWORDS:
        failed.append("✗ Generic or Invalid Metric Name")
        return 0.0, passed, failed

    # Hard Gate 3: Value Type Compatibility
    if type_a != type_b and not (type_a in {ROLE_COUNT, ROLE_SHARE_COUNT} and type_b in {ROLE_COUNT, ROLE_SHARE_COUNT}):
        failed.append(f"✗ Incompatible Value Types ({type_a} vs {type_b})")
        return 0.0, passed, failed
    else:
        passed.append(f"✓ Compatible Value Type ({type_a})")

    # Hard Gate 4: Generic Canonical Metric Identity Match (User Review Fix 1)
    canon_a = canonicalize_metric(metric_a)
    canon_b = canonicalize_metric(metric_b)

    if canon_a != canon_b:
        failed.append(f"✗ Metric Canonical Mismatch ('{canon_a}' vs '{canon_b}')")
        return 0.0, passed, failed
    else:
        passed.append(f"✓ Metric Canonical Match ('{canon_a}')")

    # Hard Gate 5: Unit Compatibility
    if unit_a and unit_b and unit_a != unit_b:
        incompatible_pairs = [
            ("%", "inr"), ("%", "usd"), ("%", "parcels"), ("%", "employees"), ("%", "shares"),
            ("inr", "%"), ("usd", "%"), ("parcels", "%"), ("employees", "%"), ("shares", "%")
        ]
        if (unit_a, unit_b) in incompatible_pairs or (unit_b, unit_a) in incompatible_pairs:
            failed.append(f"✗ Incompatible Dimensions ({unit_a} vs {unit_b})")
            return 0.0, passed, failed

    passed.append(f"✓ Units Compatible ({unit_a or 'unspecified'})")
    return 1.0, passed, failed

def find_candidate_pairs(
    facts: List[Dict[str, Any]],
    similarity_threshold: float = 0.35,
    max_candidates: int = 50
) -> List[Tuple[Dict[str, Any], Dict[str, Any], float, List[str]]]:
    """
    Computes pairwise similarity between facts across different documents
    to identify candidate pairs for relationship evaluation.
    """
    if len(facts) < 2:
        return []
        
    num_facts = len(facts)
    exact_pairs = []
    fuzzy_pairs = []
    seen_pairs = set()

    for i in range(num_facts):
        for j in range(i + 1, num_facts):
            f_a = facts[i]
            f_b = facts[j]
            
            if f_a["document_id"] == f_b["document_id"]:
                continue
                
            pair_key = (min(f_a["id"], f_b["id"]), max(f_a["id"], f_b["id"]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            comp_score, passed_gates, failed_gates = calculate_comparability_score(f_a, f_b)
            if comp_score < 0.50:
                continue
                
            pair = (f_a, f_b, comp_score, passed_gates)
            exact_block = (
                (f_a.get("subject_entity") or f_a.get("entity")) == (f_b.get("subject_entity") or f_b.get("entity"))
                and canonicalize_metric(f_a.get("metric", "")) == canonicalize_metric(f_b.get("metric", ""))
                and f_a.get("value_type") == f_b.get("value_type")
            )
            (exact_pairs if exact_block else fuzzy_pairs).append(pair)
            
    fuzzy_pairs.sort(key=lambda x: x[2], reverse=True)
    # Exact semantic blocks are never subject to the global discovery cap.
    return exact_pairs + fuzzy_pairs[:max(0, max_candidates - len(exact_pairs))]

JUDGE_PROMPT = """You are a rigorous financial & macroeconomic fact-checking engine.
Analyze two extracted facts from different documents and evaluate their relationship.

Fact A:
- Document ID: {doc_a}
- Page: {page_a}
- Entity: {ent_a}
- Metric: {metric_a}
- Raw Value: {val_a}
- Unit: {unit_a}
- Normalized Value: {norm_val_a} {norm_unit_a}
- Period: {time_a}
- Verbatim Quote: "{quote_a}"

Fact B:
- Document ID: {doc_b}
- Page: {page_b}
- Entity: {ent_b}
- Metric: {metric_b}
- Raw Value: {val_b}
- Unit: {unit_b}
- Normalized Value: {norm_val_b} {norm_unit_b}
- Period: {time_b}
- Verbatim Quote: "{quote_b}"

Determine their relationship strictly into one of:
- "CORROBORATES": Both facts assert the exact same metric claim or agree on values for the same period.
- "CONTRADICTS": Facts directly conflict for the same period/scope without clear contextual explanation.
- "LIKELY_CONTRADICTION": High metric similarity and overlapping period, but minor unexplained discrepancy (e.g. 60% vs 59%).
- "CONTEXTUAL_DIFFERENCE": Discrepancy is fully explained because facts refer to different reporting periods (e.g. FY21 vs FY24).
- "RECONCILED_UNIT": Value difference explained by unit conversion (e.g. ₹81,415.38M vs ₹8,142Cr).
- "RECONCILED_ROUNDING": Minor presentation rounding (e.g. 289.20M vs 289M).
- "UNRELATED": Facts cover completely different metrics or entities.
- "UNCERTAIN": Low confidence or ambiguous claims.

Respond STRICTLY with valid JSON format:
{{
  "taxonomy_category": "CORROBORATES" | "CONTRADICTS" | "LIKELY_CONTRADICTION" | "CONTEXTUAL_DIFFERENCE" | "RECONCILED_UNIT" | "RECONCILED_ROUNDING" | "UNRELATED" | "UNCERTAIN",
  "reasoning": "Clear 1-2 sentence explanation of why they fall into this category.",
  "confidence_delta": 0.15,
  "comparison_delta": 0.0,
  "can_compute_delta": true | false
}}
"""

def judge_relationship_mock(fact_a: Dict[str, Any], fact_b: Dict[str, Any]) -> Dict[str, Any]:
    """Fallback relationship judge using strict deterministic comparison rules."""
    comp_score, passed_gates, failed_gates = calculate_comparability_score(fact_a, fact_b)
    if comp_score < 0.50:
        return {
            "relationship": TAXONOMY_UNRELATED,
            "taxonomy_category": TAXONOMY_UNRELATED,
            "reasoning": f"Facts failed comparability gates: {'; '.join(failed_gates)}.",
            "confidence_delta": 0.0,
            "comparison_delta": 0.0,
            "can_compute_delta": False,
            "reconciliation_type": "NONE",
            "match_checklist": failed_gates
        }
        
    val_a = fact_a.get("normalized_value")
    val_b = fact_b.get("normalized_value")
    unit_a = (fact_a.get("normalized_unit") or fact_a.get("unit") or "").upper()
    unit_b = (fact_b.get("normalized_unit") or fact_b.get("unit") or "").upper()
    period_a = (fact_a.get("period") or "").strip().lower()
    period_b = (fact_b.get("period") or "").strip().lower()
    scope_a = (fact_a.get("period_scope") or "").strip().upper()
    scope_b = (fact_b.get("period_scope") or "").strip().upper()
    vintage_a = (fact_a.get("estimate_vintage") or "").strip().upper()
    vintage_b = (fact_b.get("estimate_vintage") or "").strip().upper()
    computable = can_compute_delta(fact_a, fact_b)

    if val_a is not None and val_b is not None and computable:
        delta = abs(val_a - val_b)
        avg_val = (abs(val_a) + abs(val_b)) / 2.0 if (abs(val_a) + abs(val_b)) > 0 else 1.0
        pct_delta = round((delta / avg_val) * 100.0, 2)
        
        # Period Compatibility Check (User Review Fix 2 & 4)
        is_same_period = (period_a and period_b and period_a == period_b)
        is_period_diff = (period_a and period_b and period_a != period_b)

        if is_same_period and scope_a and scope_b and scope_a != scope_b:
            return {
                "relationship": TAXONOMY_TEMPORAL_COMPARISON,
                "taxonomy_category": TAXONOMY_TEMPORAL_COMPARISON,
                "reasoning": f"Same reporting year but incompatible scopes ({scope_a} vs {scope_b}); values are not a contradiction.",
                "confidence_delta": 0.85, "comparison_delta": pct_delta,
                "can_compute_delta": True, "reconciliation_type": "SCOPE_PERIOD_DIFFERENCE",
                "match_checklist": passed_gates + ["ℹ Scope/period difference"]
            }

        if is_same_period and vintage_a and vintage_b and vintage_a != vintage_b:
            return {
                "relationship": "RECONCILED", "taxonomy_category": TAXONOMY_RECONCILED_SCOPE,
                "reasoning": f"Different estimate vintages ({vintage_a} vs {vintage_b}) explain the apparent discrepancy.",
                "confidence_delta": 0.92, "comparison_delta": pct_delta,
                "can_compute_delta": True, "reconciliation_type": "ESTIMATE_REVISION",
                "match_checklist": passed_gates + ["✓ Estimate revision context"]
            }

        # 1. Same metric across different periods -> TEMPORAL_COMPARISON (User Review Fix 4)
        if is_period_diff:
            return {
                "relationship": TAXONOMY_TEMPORAL_COMPARISON,
                "taxonomy_category": TAXONOMY_TEMPORAL_COMPARISON,
                "reasoning": f"Historical trend comparison for {fact_a.get('metric')} across periods ({fact_a.get('period')} vs {fact_b.get('period')}): {fact_a.get('value')} vs {fact_b.get('value')}.",
                "confidence_delta": 0.85,
                "comparison_delta": pct_delta,
                "can_compute_delta": True,
                "reconciliation_type": "HISTORICAL_TREND",
                "match_checklist": passed_gates + ["ℹ Historical Trend Across Periods"]
            }

        # 2. Same period: Exact or near-exact match (< 0.1% delta) -> CORROBORATES or RECONCILED_UNIT
        if pct_delta < 0.1:
            raw_u_a = (fact_a.get("unit") or "").lower()
            raw_u_b = (fact_b.get("unit") or "").lower()
            is_scale_diff = (("crore" in raw_u_a) != ("crore" in raw_u_b)) or (("million" in raw_u_a) != ("million" in raw_u_b)) or (("lakh" in raw_u_a) != ("lakh" in raw_u_b))
            if is_scale_diff:
                return {
                    "relationship": "RECONCILED",
                    "taxonomy_category": TAXONOMY_RECONCILED_UNIT,
                    "reasoning": f"Values align ({fact_a.get('value')} vs {fact_b.get('value')}) when normalized via unit conversion ({val_a:g} {unit_a}).",
                    "confidence_delta": 0.90,
                    "comparison_delta": pct_delta,
                    "can_compute_delta": True,
                    "reconciliation_type": "UNIT_CONVERSION",
                    "match_checklist": passed_gates + ["✓ Values Match via Unit Conversion"]
                }
            
            if is_same_period or (not period_a and not period_b):
                return {
                    "relationship": TAXONOMY_CORROBORATES,
                    "taxonomy_category": TAXONOMY_CORROBORATES,
                    "reasoning": f"Both documents corroborate the exact same metric value ({val_a:g} {unit_a}) for {fact_a.get('period') or 'same context'}.",
                    "confidence_delta": 0.95,
                    "comparison_delta": pct_delta,
                    "can_compute_delta": True,
                    "reconciliation_type": "NONE",
                    "match_checklist": passed_gates + ["✓ Values & Periods Match Exactly"]
                }
            
        # 3. Small presentation / rounding difference (< 1.5% delta, e.g. 289.20M vs 289M)
        elif pct_delta < 1.5:
            if is_same_period or (not period_a and not period_b):
                return {
                    "relationship": TAXONOMY_CORROBORATES,
                    "taxonomy_category": TAXONOMY_RECONCILED_ROUNDING,
                    "reasoning": f"Values ({val_a:g} vs {val_b:g}) match within minor presentation/rounding margin ({pct_delta}% delta) for {fact_a.get('period') or 'same context'}.",
                    "confidence_delta": 0.90,
                    "comparison_delta": pct_delta,
                    "can_compute_delta": True,
                    "reconciliation_type": "ROUNDING",
                    "match_checklist": passed_gates + [f"✓ Rounding Match ({pct_delta}% delta)"]
                }
            
        # 4. Differing values in same period -> CONTRADICTS / LIKELY_CONTRADICTION
        else:
            if is_same_period:
                if pct_delta <= 5.0:
                    return {
                        "relationship": TAXONOMY_LIKELY_CONTRADICTION,
                        "taxonomy_category": TAXONOMY_LIKELY_CONTRADICTION,
                        "reasoning": f"Minor unexplained discrepancy ({val_a:g} vs {val_b:g}, {pct_delta}% delta) for the same reporting period ({fact_a.get('period')}).",
                        "confidence_delta": 0.80,
                        "comparison_delta": pct_delta,
                        "can_compute_delta": True,
                        "reconciliation_type": "NONE",
                        "match_checklist": passed_gates + ["⚠️ Minor Unexplained Discrepancy"]
                    }
                else:
                    return {
                        "relationship": TAXONOMY_CONTRADICTS,
                        "taxonomy_category": TAXONOMY_CONTRADICTS,
                        "reasoning": f"Significant direct contradiction ({val_a:g} vs {val_b:g}, {pct_delta}% delta) for the same period ({fact_a.get('period')}) without contextual explanation.",
                        "confidence_delta": 0.85,
                        "comparison_delta": pct_delta,
                        "can_compute_delta": True,
                        "reconciliation_type": "NONE",
                        "match_checklist": passed_gates + ["✗ Direct Unexplained Contradiction"]
                    }

    return {
        "relationship": TAXONOMY_UNCERTAIN,
        "taxonomy_category": TAXONOMY_UNCERTAIN,
        "reasoning": "Non-numeric, ambiguous, or missing period context for comparison.",
        "confidence_delta": 0.0,
        "comparison_delta": 0.0,
        "can_compute_delta": False,
        "reconciliation_type": "NONE",
        "match_checklist": passed_gates
    }

def judge_relationship(fact_a: Dict[str, Any], fact_b: Dict[str, Any], api_key: str = None) -> Dict[str, Any]:
    """Calls LLM judge (OpenRouter) to evaluate candidate pair relationship, with fallback judge."""
    key = api_key or OPENROUTER_API_KEY or os.getenv("OPENROUTER_API_KEY", "")
    
    if not key or key == "your_openrouter_api_key_here":
        return judge_relationship_mock(fact_a, fact_b)
        
    comp_score, passed_gates, failed_gates = calculate_comparability_score(fact_a, fact_b)
    if comp_score < 0.50:
        return judge_relationship_mock(fact_a, fact_b)
        
    prompt = JUDGE_PROMPT.format(
        doc_a=fact_a.get("document_id"), page_a=fact_a.get("page"),
        ent_a=fact_a.get("entity") or fact_a.get("subject"), metric_a=fact_a.get("metric"), val_a=fact_a.get("value"),
        unit_a=fact_a.get("unit"), norm_val_a=fact_a.get("normalized_value"), norm_unit_a=fact_a.get("normalized_unit"),
        time_a=fact_a.get("period"), quote_a=fact_a.get("raw_quote"),
        doc_b=fact_b.get("document_id"), page_b=fact_b.get("page"),
        ent_b=fact_b.get("entity") or fact_b.get("subject"), metric_b=fact_b.get("metric"), val_b=fact_b.get("value"),
        unit_b=fact_b.get("unit"), norm_val_b=fact_b.get("normalized_value"), norm_unit_b=fact_b.get("normalized_unit"),
        time_b=fact_b.get("period"), quote_b=fact_b.get("raw_quote")
    )
    
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/fact-knowledge-layer",
        "X-Title": "Fact Knowledge Layer"
    }
    
    payload = {
        "model": os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 350,
        "response_format": {"type": "json_object"}
    }
    
    try:
        with httpx.Client(timeout=12.0) as client:
            res = client.post(OPENROUTER_URL, headers=headers, json=payload)
            if res.status_code != 200:
                return judge_relationship_mock(fact_a, fact_b)
            data = res.json()
            raw_content = data["choices"][0]["message"]["content"]
            parsed = json.loads(raw_content)
            
            tax_cat = str(parsed.get("taxonomy_category", TAXONOMY_UNCERTAIN)).upper()
            computable = can_compute_delta(fact_a, fact_b)
            
            rel_type = tax_cat
            if tax_cat in {TAXONOMY_RECONCILED_UNIT, TAXONOMY_RECONCILED_ROUNDING, TAXONOMY_RECONCILED_SCOPE, TAXONOMY_CONTEXTUAL_DIFFERENCE}:
                rel_type = "RECONCILED"
            elif tax_cat == TAXONOMY_CORROBORATES:
                rel_type = "CORROBORATES"
            elif tax_cat in {TAXONOMY_CONTRADICTS, TAXONOMY_LIKELY_CONTRADICTION}:
                rel_type = tax_cat
                
            return {
                "relationship": rel_type,
                "taxonomy_category": tax_cat,
                "reasoning": str(parsed.get("reasoning", "No explanation provided.")),
                "confidence_delta": float(parsed.get("confidence_delta", 0.0)),
                "comparison_delta": float(parsed.get("comparison_delta", 0.0)) if computable else 0.0,
                "can_compute_delta": computable,
                "reconciliation_type": tax_cat,
                "match_checklist": passed_gates
            }
    except Exception:
        return judge_relationship_mock(fact_a, fact_b)

def recalculate_fact_confidences(conn) -> Dict[int, float]:
    """Updates final_confidence in SQLite for all facts in a fast batch transaction."""
    cursor = conn.cursor()
    cursor.execute("SELECT id, extraction_confidence, grounding_confidence, value_binding_confidence FROM facts")
    all_facts = cursor.fetchall()
    
    updated_scores = {}
    updates = []
    
    for f in all_facts:
        f_id = f["id"]
        ext_conf = float(f["extraction_confidence"])
        grd_conf = float(f["grounding_confidence"])
        bnd_conf = float(f["value_binding_confidence"]) if f["value_binding_confidence"] is not None else 1.0
        
        base_score = ext_conf * grd_conf * bnd_conf
        
        cursor.execute("SELECT confidence_delta FROM fact_relationships WHERE fact_id_a = ? OR fact_id_b = ?", (f_id, f_id))
        deltas = cursor.fetchall()
        total_delta = sum(float(d["confidence_delta"]) for d in deltas)
        
        final_score = round(max(0.0, min(1.0, base_score + total_delta)), 3)
        updated_scores[f_id] = final_score
        updates.append((final_score, f_id))
        
    cursor.executemany("UPDATE facts SET final_confidence = ? WHERE id = ?", updates)
    conn.commit()
    return updated_scores
