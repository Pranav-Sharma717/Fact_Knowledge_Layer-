import os
import json
import httpx
import re
from typing import List, Dict, Any, Tuple
from dotenv import load_dotenv

from app.validation import UNIT_KEYWORDS, GENERIC_METRICS

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_EMBED_MODEL = None

def get_embedding_model():
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            print("[INFO] Loading local sentence-transformer model 'all-MiniLM-L6-v2'...")
            _EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception:
            try:
                from sklearn.feature_extraction.text import TfidfVectorizer
                print("[INFO] SentenceTransformer unavailable. Using TF-IDF vectorizer fallback.")
                _EMBED_MODEL = "tfidf"
            except Exception:
                print("[INFO] Using pure Python string overlap vectorizer fallback.")
                _EMBED_MODEL = "simple"
    return _EMBED_MODEL

def simple_similarity(str1: str, str2: str) -> float:
    """Fallback cosine similarity based on word set overlap."""
    w1 = set(str1.lower().split())
    w2 = set(str2.lower().split())
    if not w1 or not w2:
        return 0.0
    inter = w1.intersection(w2)
    return len(inter) / ((len(w1) ** 0.5) * (len(w2) ** 0.5))

def calculate_comparability_score(fact_a: Dict[str, Any], fact_b: Dict[str, Any]) -> float:
    """
    Evaluates whether two facts are genuinely comparable.
    Returns a score between 0.0 (uncomparable) and 1.0 (highly comparable).
    """
    metric_a = (fact_a.get("metric") or "").lower().strip()
    metric_b = (fact_b.get("metric") or "").lower().strip()
    
    entity_a = (fact_a.get("entity") or fact_a.get("subject") or "").lower().strip()
    entity_b = (fact_b.get("entity") or fact_b.get("subject") or "").lower().strip()

    # Rule 1: Generic or unit metrics cannot be compared
    if not metric_a or not metric_b or metric_a in GENERIC_METRICS or metric_b in GENERIC_METRICS or metric_a in UNIT_KEYWORDS or metric_b in UNIT_KEYWORDS:
        return 0.0

    # Rule 2: Require non-null numeric values or valid assertions
    val_a = fact_a.get("normalized_value")
    val_b = fact_b.get("normalized_value")
    if val_a is None or val_b is None:
        return 0.0

    # Rule 3: Word token overlap on metric names
    stopwords = {"the", "and", "of", "in", "for", "to", "a", "from", "on", "rate", "total", "states", "shows", "claim", "limited"}
    words_a = set(re.findall(r'\w+', metric_a)) - stopwords
    words_b = set(re.findall(r'\w+', metric_b)) - stopwords

    if not words_a or not words_b or not words_a.intersection(words_b):
        return 0.0

    # Rule 4: Unit compatibility
    unit_a = (fact_a.get("normalized_unit") or fact_a.get("unit") or "").lower().strip()
    unit_b = (fact_b.get("normalized_unit") or fact_b.get("unit") or "").lower().strip()
    if unit_a and unit_b and unit_a != unit_b:
        incompatible_pairs = [
            ("%", "inr"), ("%", "usd"), ("%", "parcels"), ("%", "employees"),
            ("inr", "%"), ("usd", "%"), ("parcels", "%"), ("employees", "%")
        ]
        if (unit_a, unit_b) in incompatible_pairs or (unit_b, unit_a) in incompatible_pairs:
            return 0.0

    return simple_similarity(f"{entity_a} {metric_a}", f"{entity_b} {metric_b}")

def find_candidate_pairs(
    facts: List[Dict[str, Any]],
    similarity_threshold: float = 0.35,
    max_candidates: int = 50
) -> List[Tuple[Dict[str, Any], Dict[str, Any], float]]:
    """
    Computes pairwise similarity between facts across different documents
    to identify candidate pairs for relationship evaluation.
    """
    if len(facts) < 2:
        return []
        
    num_facts = len(facts)
    candidate_pairs = []
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

            comp_score = calculate_comparability_score(f_a, f_b)
            if comp_score < 0.25:
                continue
                
            candidate_pairs.append((f_a, f_b, comp_score))
            
    candidate_pairs.sort(key=lambda x: x[2], reverse=True)
    return candidate_pairs[:max_candidates]

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
- "LIKELY_CONTRADICTION": High metric similarity and overlapping period, but minor unexplained discrepancy.
- "RECONCILED": Value difference explainable by context (different time periods, fiscal vs calendar year, unit conversion, restatements/audits, or scope).
- "UNRELATED": Facts cover completely different metrics or entities.
- "UNCERTAIN": Low confidence or ambiguous claims.

Respond STRICTLY with valid JSON format:
{{
  "relationship": "CORROBORATES" | "CONTRADICTS" | "LIKELY_CONTRADICTION" | "RECONCILED" | "UNRELATED" | "UNCERTAIN",
  "reasoning": "Clear 1-2 sentence explanation of why they fall into this category.",
  "confidence_delta": 0.15,
  "comparison_delta": 0.0,
  "reconciliation_type": "UNIT_CONVERSION" | "ROUNDING" | "PERIOD_DIFFERENCE" | "SCOPE_DIFFERENCE" | "AUDIT_RESTATEMENT" | "NONE"
}}
"""

def judge_relationship_mock(fact_a: Dict[str, Any], fact_b: Dict[str, Any]) -> Dict[str, Any]:
    """Fallback relationship judge using strict deterministic comparison rules."""
    comp_score = calculate_comparability_score(fact_a, fact_b)
    if comp_score < 0.25:
        return {
            "relationship": "UNRELATED",
            "reasoning": "Facts concern distinct metrics or entities with no genuine basis for comparison.",
            "confidence_delta": 0.0,
            "comparison_delta": 0.0,
            "reconciliation_type": "NONE"
        }
        
    val_a = fact_a.get("normalized_value")
    val_b = fact_b.get("normalized_value")
    unit_a = (fact_a.get("normalized_unit") or fact_a.get("unit") or "").upper()
    unit_b = (fact_b.get("normalized_unit") or fact_b.get("unit") or "").upper()
    period_a = (fact_a.get("period") or "").strip().lower()
    period_b = (fact_b.get("period") or "").strip().lower()

    if val_a is not None and val_b is not None:
        delta = abs(val_a - val_b)
        avg_val = (abs(val_a) + abs(val_b)) / 2.0 if (abs(val_a) + abs(val_b)) > 0 else 1.0
        pct_delta = round((delta / avg_val) * 100.0, 2)
        
        # Exact or near-exact match (< 0.1% delta)
        if pct_delta < 0.1:
            raw_u_a = (fact_a.get("unit") or "").lower()
            raw_u_b = (fact_b.get("unit") or "").lower()
            if raw_u_a != raw_u_b and raw_u_a and raw_u_b and raw_u_a not in raw_u_b and raw_u_b not in raw_u_a:
                return {
                    "relationship": "RECONCILED",
                    "reasoning": f"Values align ({fact_a.get('value')} vs {fact_b.get('value')}) when normalized via unit conversion ({val_a:g} {unit_a}).",
                    "confidence_delta": 0.15,
                    "comparison_delta": pct_delta,
                    "reconciliation_type": "UNIT_CONVERSION"
                }
            if period_a and period_b and period_a != period_b:
                return {
                    "relationship": "RECONCILED",
                    "reasoning": f"Identical value ({val_a:g}) reported across different time periods ({fact_a.get('period')} vs {fact_b.get('period')}).",
                    "confidence_delta": 0.10,
                    "comparison_delta": pct_delta,
                    "reconciliation_type": "PERIOD_DIFFERENCE"
                }
            return {
                "relationship": "CORROBORATES",
                "reasoning": f"Both documents corroborate the exact same metric value ({val_a:g} {unit_a}).",
                "confidence_delta": 0.20,
                "comparison_delta": pct_delta,
                "reconciliation_type": "NONE"
            }
            
        # Small rounding difference (< 1.5% delta)
        elif pct_delta < 1.5:
            return {
                "relationship": "RECONCILED",
                "reasoning": f"Values ({val_a:g} vs {val_b:g}) match within minor rounding margin ({pct_delta}% delta).",
                "confidence_delta": 0.10,
                "comparison_delta": pct_delta,
                "reconciliation_type": "ROUNDING"
            }
            
        # Differing values
        else:
            if period_a and period_b and period_a != period_b:
                return {
                    "relationship": "RECONCILED",
                    "reasoning": f"Value discrepancy ({val_a:g} vs {val_b:g}, {pct_delta}% delta) is reconciled by differing reporting periods ({fact_a.get('period')} vs {fact_b.get('period')}).",
                    "confidence_delta": 0.05,
                    "comparison_delta": pct_delta,
                    "reconciliation_type": "PERIOD_DIFFERENCE"
                }
            elif pct_delta < 10.0:
                return {
                    "relationship": "LIKELY_CONTRADICTION",
                    "reasoning": f"Moderate unexplained discrepancy ({val_a:g} vs {val_b:g}, {pct_delta}% delta) for the same reporting period.",
                    "confidence_delta": -0.15,
                    "comparison_delta": pct_delta,
                    "reconciliation_type": "NONE"
                }
            else:
                return {
                    "relationship": "CONTRADICTS",
                    "reasoning": f"Significant direct contradiction ({val_a:g} vs {val_b:g}, {pct_delta}% delta) without contextual explanation.",
                    "confidence_delta": -0.30,
                    "comparison_delta": pct_delta,
                    "reconciliation_type": "NONE"
                }
                
    return {
        "relationship": "UNCERTAIN",
        "reasoning": "Non-numeric or ambiguous comparison.",
        "confidence_delta": 0.0,
        "comparison_delta": 0.0,
        "reconciliation_type": "NONE"
    }

def judge_relationship(fact_a: Dict[str, Any], fact_b: Dict[str, Any], api_key: str = None) -> Dict[str, Any]:
    """Calls LLM judge (OpenRouter) to evaluate candidate pair relationship, with fallback judge."""
    key = api_key or OPENROUTER_API_KEY or os.getenv("OPENROUTER_API_KEY", "")
    model_name = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    
    if not key or key == "your_openrouter_api_key_here":
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
        "model": model_name,
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
            
            rel_type = str(parsed.get("relationship", "UNCERTAIN")).upper()
            if rel_type not in {"CORROBORATES", "CONTRADICTS", "LIKELY_CONTRADICTION", "RECONCILED", "UNRELATED", "UNCERTAIN"}:
                rel_type = "UNCERTAIN"
                
            return {
                "relationship": rel_type,
                "reasoning": str(parsed.get("reasoning", "No explanation provided.")),
                "confidence_delta": float(parsed.get("confidence_delta", 0.0)),
                "comparison_delta": float(parsed.get("comparison_delta", 0.0)),
                "reconciliation_type": str(parsed.get("reconciliation_type", "NONE")).upper()
            }
    except Exception:
        return judge_relationship_mock(fact_a, fact_b)

def recalculate_fact_confidences(conn) -> Dict[int, float]:
    """Updates final_confidence in SQLite for all facts in a fast batch transaction."""
    cursor = conn.cursor()
    cursor.execute("SELECT id, extraction_confidence, grounding_confidence FROM facts")
    all_facts = cursor.fetchall()
    
    updated_scores = {}
    updates = []
    
    for f in all_facts:
        f_id = f["id"]
        base_score = float(f["extraction_confidence"]) * float(f["grounding_confidence"])
        
        cursor.execute("SELECT confidence_delta FROM fact_relationships WHERE fact_id_a = ? OR fact_id_b = ?", (f_id, f_id))
        deltas = cursor.fetchall()
        total_delta = sum(float(d["confidence_delta"]) for d in deltas)
        
        final_score = round(max(0.0, min(1.0, base_score + total_delta)), 3)
        updated_scores[f_id] = final_score
        updates.append((final_score, f_id))
        
    cursor.executemany("UPDATE facts SET final_confidence = ? WHERE id = ?", updates)
    conn.commit()
    return updated_scores
