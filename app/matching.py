import os
import json
import httpx
from typing import List, Dict, Any, Tuple
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Global lazy-loaded embedding model
_EMBED_MODEL = None

def get_embedding_model():
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            print("[INFO] Loading local sentence-transformer model 'all-MiniLM-L6-v2'...")
            _EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception as e:
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

def find_candidate_pairs(facts: List[Dict[str, Any]], similarity_threshold: float = 0.35) -> List[Tuple[Dict[str, Any], Dict[str, Any], float]]:
    """
    Computes pairwise similarity between facts across different documents
    to identify candidate pairs for relationship evaluation.
    """
    if len(facts) < 2:
        return []
        
    fact_strings = [
        f"Subject: {f['subject']} | Predicate: {f['predicate']} | Value: {f['value']} | Unit: {f.get('unit')} | Time: {f.get('time_scope')}"
        for f in facts
    ]
    
    model = get_embedding_model()
    num_facts = len(facts)
    candidate_pairs = []
    
    if model != "tfidf" and model != "simple" and hasattr(model, "encode"):
        import numpy as np
        embeddings = model.encode(fact_strings, convert_to_numpy=True, normalize_embeddings=True)
        sim_matrix = np.dot(embeddings, embeddings.T)
        for i in range(num_facts):
            for j in range(i + 1, num_facts):
                if facts[i]["document_id"] != facts[j]["document_id"] or facts[i]["id"] != facts[j]["id"]:
                    score = float(sim_matrix[i, j])
                    if score >= similarity_threshold:
                        candidate_pairs.append((facts[i], facts[j], score))
    elif model == "tfidf":
        import numpy as np
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        vec = TfidfVectorizer()
        mat = vec.fit_transform(fact_strings)
        sim_matrix = cosine_similarity(mat, mat)
        for i in range(num_facts):
            for j in range(i + 1, num_facts):
                if facts[i]["document_id"] != facts[j]["document_id"] or facts[i]["id"] != facts[j]["id"]:
                    score = float(sim_matrix[i, j])
                    if score >= similarity_threshold:
                        candidate_pairs.append((facts[i], facts[j], score))
    else:
        # Simple word set fallback
        for i in range(num_facts):
            for j in range(i + 1, num_facts):
                if facts[i]["document_id"] != facts[j]["document_id"] or facts[i]["id"] != facts[j]["id"]:
                    score = simple_similarity(fact_strings[i], fact_strings[j])
                    if score >= similarity_threshold:
                        candidate_pairs.append((facts[i], facts[j], score))
                        
    candidate_pairs.sort(key=lambda x: x[2], reverse=True)
    return candidate_pairs

JUDGE_PROMPT = """You are a rigorous financial & macroeconomic fact-checking engine.
Analyze two extracted facts from different documents and evaluate their relationship.

Fact A:
- Document ID: {doc_a}
- Page: {page_a}
- Subject: {sub_a}
- Predicate: {pred_a}
- Value: {val_a}
- Unit: {unit_a}
- Time Scope: {time_a}
- Verbatim Quote: "{quote_a}"

Fact B:
- Document ID: {doc_b}
- Page: {page_b}
- Subject: {sub_b}
- Predicate: {pred_b}
- Value: {val_b}
- Unit: {unit_b}
- Time Scope: {time_b}
- Verbatim Quote: "{quote_b}"

Determine their relationship:
1. "corroborates": Both facts assert the exact same claim or agree on metrics/events.
2. "contradicts": Facts directly conflict without a clear contextual explanation (e.g. conflicting numbers for the exact same year and scope).
3. "reconciled": Contradiction explainable by context (different time periods, fiscal vs calendar year, restatements/audits, scope, or units).
4. "unrelated": Facts cover completely different topics.

Respond STRICTLY with valid JSON format:
{{
  "relationship": "corroborates" | "contradicts" | "reconciled" | "unrelated",
  "reasoning": "Clear 1-2 sentence explanation of why they corroborate, contradict, or are reconciled by context.",
  "confidence_delta": 0.15
}}
"""

def judge_relationship_mock(fact_a: Dict[str, Any], fact_b: Dict[str, Any]) -> Dict[str, Any]:
    """Fallback relationship judge if no valid API key is set."""
    quote_a = fact_a.get("raw_quote", "").lower()
    quote_b = fact_b.get("raw_quote", "").lower()
    val_a = str(fact_a.get("value", "")).lower()
    val_b = str(fact_b.get("value", "")).lower()
    
    if val_a == val_b or (val_a in quote_b and val_b in quote_a):
        return {
            "relationship": "corroborates",
            "reasoning": "Both facts state identical values across source documents.",
            "confidence_delta": 0.15
        }
    elif fact_a.get("time_scope") != fact_b.get("time_scope"):
        return {
            "relationship": "reconciled",
            "reasoning": f"Apparent value difference is reconciled by differing time periods ({fact_a.get('time_scope')} vs {fact_b.get('time_scope')}).",
            "confidence_delta": 0.05
        }
    else:
        return {
            "relationship": "contradicts",
            "reasoning": "Facts present conflicting values for the same scope without explicit reconciliation in quote.",
            "confidence_delta": -0.25
        }

def judge_relationship(fact_a: Dict[str, Any], fact_b: Dict[str, Any], api_key: str = None) -> Dict[str, Any]:
    """Calls LLM judge (OpenRouter) to evaluate candidate pair relationship."""
    key = api_key or OPENROUTER_API_KEY or os.getenv("OPENROUTER_API_KEY", "")
    model_name = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    
    if not key or key == "your_openrouter_api_key_here":
        return judge_relationship_mock(fact_a, fact_b)
        
    prompt = JUDGE_PROMPT.format(
        doc_a=fact_a.get("document_id"), page_a=fact_a.get("page"),
        sub_a=fact_a.get("subject"), pred_a=fact_a.get("predicate"), val_a=fact_a.get("value"),
        unit_a=fact_a.get("unit"), time_a=fact_a.get("time_scope"), quote_a=fact_a.get("raw_quote"),
        doc_b=fact_b.get("document_id"), page_b=fact_b.get("page"),
        sub_b=fact_b.get("subject"), pred_b=fact_b.get("predicate"), val_b=fact_b.get("value"),
        unit_b=fact_b.get("unit"), time_b=fact_b.get("time_scope"), quote_b=fact_b.get("raw_quote")
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
        "response_format": {"type": "json_object"}
    }
    
    try:
        with httpx.Client(timeout=30.0) as client:
            res = client.post(OPENROUTER_URL, headers=headers, json=payload)
            if res.status_code == 401:
                return judge_relationship_mock(fact_a, fact_b)
            res.raise_for_status()
            data = res.json()
            raw_content = data["choices"][0]["message"]["content"]
            parsed = json.loads(raw_content)
            
            return {
                "relationship": parsed.get("relationship", "unrelated").lower(),
                "reasoning": parsed.get("reasoning", "No explanation provided."),
                "confidence_delta": float(parsed.get("confidence_delta", 0.0))
            }
    except Exception as e:
        print(f"[ERROR] LLM Relationship Judging failed: {e}. Falling back to mock judge.")
        return judge_relationship_mock(fact_a, fact_b)

def recalculate_fact_confidences(conn) -> Dict[str, float]:
    """
    Updates final_confidence in SQLite for all facts based on evidence grounding,
    corroborations, and un-reconciled contradictions.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT id, extraction_confidence, grounding_confidence FROM facts")
    all_facts = cursor.fetchall()
    
    updated_scores = {}
    for f in all_facts:
        f_id = f["id"]
        base_score = float(f["extraction_confidence"]) * float(f["grounding_confidence"])
        
        cursor.execute("SELECT confidence_delta FROM fact_relationships WHERE fact_id_a = ? OR fact_id_b = ?", (f_id, f_id))
        deltas = cursor.fetchall()
        total_delta = sum(float(d["confidence_delta"]) for d in deltas)
        
        final_score = round(max(0.0, min(1.0, base_score + total_delta)), 3)
        updated_scores[f_id] = final_score
        cursor.execute("UPDATE facts SET final_confidence = ? WHERE id = ?", (final_score, f_id))
        
    conn.commit()
    return updated_scores
