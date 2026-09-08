import os
import json
import httpx
import re
from typing import List, Dict, Any, Tuple
from dotenv import load_dotenv

from app.normalization import normalize_fact
from app.validation import validate_fact_candidate, is_header_or_unit_label

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are an expert fact-extraction engine for a corporate intelligence and financial analysis system.
Your job is to read a document chunk and extract all discrete, atomic facts present in the text.

Guidelines:
1. Every fact must be atomic, precise, and grounded in the source text.
2. Grounding is CRITICAL: You MUST supply a 'raw_quote' field containing the EXACT VERBATIM substring from the text supporting the fact.
3. Schema for each fact:
   - "entity": Specific entity or organization described (e.g. "Delhivery", "India", "Express Parcel Service"), or "Unknown Entity" if implicit.
   - "metric": Specific metric or phenomenon (e.g. "Revenue from Operations", "EBITDA Margin", "Express Parcel Volume", "GDP Growth Rate", "Employee Attrition Rate").
   - "predicate": Relation/verb (e.g. "was", "reached", "grew by", "reported as").
   - "value": Raw value as stated in text (e.g. "₹81,415.38 million", "289.20 million", "7.2%").
   - "unit": Unit of measurement if applicable (e.g. "INR", "parcels", "%", "employees"), or null.
   - "period": Time period or fiscal year if specified (e.g. "FY 2023", "FY 2024", "Q1 FY24"), or null.
   - "as_of_date": Exact date if mentioned (e.g. "March 31, 2023"), or null.
   - "scope": Operational scope or segment (e.g. "Restated Consolidated", "Standalone", "Global"), or null.
   - "qualifiers": Any essential qualification or context, or null.
   - "raw_quote": Exact verbatim quote copied from the text chunk supporting this claim.
   - "extraction_confidence": Float between 0.0 and 1.0 reflecting how clearly the fact is stated.

Respond strictly with valid JSON format:
{
  "facts": [
    {
      "entity": "...",
      "metric": "...",
      "predicate": "...",
      "value": "...",
      "unit": "...",
      "period": "...",
      "as_of_date": "...",
      "scope": "...",
      "qualifiers": "...",
      "raw_quote": "...",
      "extraction_confidence": 0.95
    }
  ]
}
"""

def normalize_period_str(period: str) -> str:
    if not period:
        return ""
    p = period.upper().strip()
    p = re.sub(r'FY\s*(\d{2})\b', r'FY 20\1', p)
    p = re.sub(r'FY\s*(\d{4})\b', r'FY \1', p)
    return p

def infer_doc_defaults(doc_filename: str) -> Tuple[str, str]:
    """Infers fallback entity and period from document filename."""
    fn = (doc_filename or "").lower()
    
    # Infer entity
    if "delhivery" in fn:
        entity = "Delhivery Limited"
    elif "rbi" in fn:
        entity = "Reserve Bank of India"
    elif "economic-survey" in fn or "macroeconomy" in fn:
        entity = "India Macroeconomy"
    elif "imf" in fn:
        entity = "IMF / India"
    else:
        entity = "Document Entity"
        
    # Infer period
    if "fy24" in fn or "2024-25" in fn or "2024" in fn:
        period = "FY 2024"
    elif "fy23" in fn or "2023" in fn:
        period = "FY 2023"
    elif "2022" in fn or "prospectus" in fn:
        period = "FY 2021"
    elif "2025" in fn:
        period = "FY 2025"
    else:
        period = "Reporting Period"
        
    return entity, period

def verify_grounding(raw_quote: str, chunk_text: str) -> float:
    """Verifies evidence grounding by checking if raw_quote matches chunk_text."""
    if not raw_quote or not chunk_text:
        return 0.0
    if raw_quote in chunk_text:
        return 1.0
    quote_clean = raw_quote.strip()
    if quote_clean.lower() in chunk_text.lower():
        return 0.85
    norm_quote = re.sub(r'\s+', ' ', quote_clean).lower()
    norm_chunk = re.sub(r'\s+', ' ', chunk_text).lower()
    if norm_quote in norm_chunk:
        return 0.70
    return 0.0

def extract_facts_from_chunk_mock(
    chunk_text: str,
    page_number: int,
    doc_filename: str = ""
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fallback rule-based mock extractor used when LLM API is unavailable."""
    default_entity, default_period = infer_doc_defaults(doc_filename)
    candidates = []
    lines = [line.strip() for line in chunk_text.split('\n') if line.strip()]
    
    for line in lines:
        if is_header_or_unit_label(line) or line.lower() in {"million", "crore", "lakh", "billion", "%", "(₹ in million)"}:
            candidates.append({
                "entity": default_entity,
                "metric": "Table Unit Header",
                "predicate": "states",
                "value": line,
                "unit": None,
                "period": default_period,
                "raw_quote": line,
                "extraction_confidence": 0.85
            })
            continue

        if any(kw in line.lower() for kw in ["revenue", "$", "%", "employees", "crore", "billion", "million", "growth", "headcount", "profit", "expenditure", "ebitda", "volume", "gdp", "attrition"]):
            num_match = re.search(r'([-+]?\d+(?:,\d+)*(?:\.\d+)?)', line)
            val_str = num_match.group(1) if num_match else line
            
            metric_part = re.sub(r'[-+]?\d+(?:,\d+)*(?:\.\d+)?', '', line).strip(' :-₹$%,()')
            metric_name = metric_part if len(metric_part) > 3 else "General Metric"
            
            period_match = re.search(r'\b(FY\s?\d{2,4}|Q[1-4]\s?FY?\d{2,4}|20\d{2})\b', line, re.IGNORECASE)
            period_str = normalize_period_str(period_match.group(1)) if period_match else default_period

            candidates.append({
                "entity": default_entity,
                "metric": metric_name,
                "predicate": "states",
                "value": val_str,
                "unit": "INR" if ("₹" in line or "inr" in line.lower()) else ("%" if "%" in line else None),
                "period": period_str,
                "raw_quote": line,
                "extraction_confidence": 0.85
            })

    valid_facts = []
    rejected_extractions = []

    for cand in candidates:
        norm = normalize_fact(cand)
        cand.update({
            "numeric_value": norm["numeric_value"],
            "normalized_value": norm["normalized_value"],
            "normalized_unit": norm["normalized_unit"],
            "subject": cand.get("entity", default_entity)
        })
        
        val_res = validate_fact_candidate(cand)
        
        raw_quote = cand.get("raw_quote", "")
        ground_conf = verify_grounding(raw_quote, chunk_text)
        ext_conf = float(cand.get("extraction_confidence", 0.85))
        final_conf = round(ext_conf * ground_conf, 3)
        cand["grounding_confidence"] = ground_conf
        cand["final_confidence"] = final_conf
        cand["page"] = page_number
        cand["extraction_method"] = "fallback"

        if val_res["valid"]:
            cand["validation_status"] = "valid"
            cand["validation_notes"] = None
            valid_facts.append(cand)
        else:
            rejected_extractions.append({
                "page": page_number,
                "candidate_text": cand["value"] or raw_quote,
                "attempted_extraction": json.dumps(cand),
                "failure_type": val_res["failure_type"],
                "rejection_reason": val_res["rejection_reason"]
            })

    return valid_facts, rejected_extractions

def extract_facts_from_chunk(
    chunk_text: str,
    page_number: int,
    api_key: str = None,
    model: str = None,
    doc_filename: str = ""
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str, List[str]]:
    """
    Returns (valid_facts, rejected_extractions, extraction_method, warnings)
    extraction_method: "llm" or "fallback"
    """
    default_entity, default_period = infer_doc_defaults(doc_filename)
    key = api_key or OPENROUTER_API_KEY or os.getenv("OPENROUTER_API_KEY", "")
    selected_model = model or os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    
    if not key or key == "your_openrouter_api_key_here":
        valid, rejected = extract_facts_from_chunk_mock(chunk_text, page_number, doc_filename=doc_filename)
        return valid, rejected, "fallback", ["OpenRouter API Key not set. Using rule-based fallback extractor."]

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/fact-knowledge-layer",
        "X-Title": "Fact Knowledge Layer"
    }
    
    payload = {
        "model": selected_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Extract facts from the following text chunk (Document: {doc_filename}, Page {page_number}):\n\n{chunk_text}"}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }
    
    try:
        with httpx.Client(timeout=15.0) as client:
            res = client.post(OPENROUTER_URL, headers=headers, json=payload)
            if res.status_code != 200:
                valid, rejected = extract_facts_from_chunk_mock(chunk_text, page_number, doc_filename=doc_filename)
                return valid, rejected, "fallback", [f"LLM API returned status {res.status_code}. Fallback extractor used."]
                
            data = res.json()
            raw_content = data["choices"][0]["message"]["content"]
            parsed = json.loads(raw_content)
            extracted_facts = parsed.get("facts", [])
            
            valid_facts = []
            rejected_extractions = []
            
            for f in extracted_facts:
                raw_quote = f.get("raw_quote", "")
                ext_conf = float(f.get("extraction_confidence", 0.9))
                ground_conf = verify_grounding(raw_quote, chunk_text)
                final_conf = round(ext_conf * ground_conf, 3)
                
                cand = {
                    "entity": f.get("entity") or f.get("subject") or default_entity,
                    "subject": f.get("entity") or f.get("subject") or default_entity,
                    "metric": f.get("metric") or "General Assertion",
                    "predicate": f.get("predicate", "states"),
                    "value": str(f.get("value", "")),
                    "unit": f.get("unit"),
                    "period": f.get("period") or f.get("time_scope") or default_period,
                    "as_of_date": f.get("as_of_date"),
                    "scope": f.get("scope"),
                    "qualifiers": f.get("qualifiers"),
                    "raw_quote": raw_quote,
                    "page": page_number,
                    "extraction_confidence": ext_conf,
                    "grounding_confidence": ground_conf,
                    "final_confidence": final_conf,
                    "extraction_method": "llm"
                }
                
                norm = normalize_fact(cand)
                cand.update({
                    "numeric_value": norm["numeric_value"],
                    "normalized_value": norm["normalized_value"],
                    "normalized_unit": norm["normalized_unit"],
                })
                
                val_res = validate_fact_candidate(cand)
                if val_res["valid"]:
                    cand["validation_status"] = "valid"
                    cand["validation_notes"] = None
                    valid_facts.append(cand)
                else:
                    rejected_extractions.append({
                        "page": page_number,
                        "candidate_text": cand["value"] or raw_quote,
                        "attempted_extraction": json.dumps(cand),
                        "failure_type": val_res["failure_type"],
                        "rejection_reason": val_res["rejection_reason"]
                    })
                    
            return valid_facts, rejected_extractions, "llm", []
    except Exception as e:
        valid, rejected = extract_facts_from_chunk_mock(chunk_text, page_number, doc_filename=doc_filename)
        return valid, rejected, "fallback", [f"LLM extraction exception ({str(e)}). Fallback extractor used."]
