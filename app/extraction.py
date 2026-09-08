import os
import json
import httpx
import re
from typing import List, Dict, Any, Tuple, Optional
from dotenv import load_dotenv

from app.normalization import normalize_fact, parse_raw_numeric
from app.validation import validate_fact_candidate, is_header_or_unit_label, UNIT_KEYWORDS, GENERIC_METRICS
from app.number_classifier import (
    classify_number_role, is_metric_value_role, detect_navigation_reference,
    ROLE_MONEY, ROLE_PERCENT, ROLE_SHARE_COUNT, ROLE_COUNT, ROLE_YEAR
)

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are an expert fact-extraction engine for a corporate intelligence and financial analysis system.
Your job is to read a document chunk and extract all discrete, atomic facts present in the text.

Guidelines:
1. Every fact must be atomic, precise, and grounded in the source text.
2. Grounding is CRITICAL: You MUST supply a 'raw_quote' field containing the EXACT VERBATIM substring from the text supporting the fact.
3. Every metric MUST be specific and descriptive (e.g. "Revenue from Operations", "Express Parcel Volume", "EBITDA Margin", "Employee Attrition Rate").
   NEVER use unit words ("million", "crore", "inr") or generic terms ("General Metric", "Amount") as the metric name.
4. Multi-value sentences MUST be split into separate facts:
   Example: "107,517,088 Equity Shares aggregating to ₹52,350 million."
   -> Fact A: entity="Delhivery Limited", metric="Offer Equity Shares", value="107,517,088", unit="shares"
   -> Fact B: entity="Delhivery Limited", metric="Offer Size", value="₹52,350 million", unit="INR million"
5. Do NOT use generic predicates like "states" or "contains". Use descriptive relation verbs (e.g. "was", "reached", "grew by", "reported as", "served as").
6. Do NOT fabricate reporting periods. Populate "period" ONLY when explicitly supported in text (e.g. "FY 2023", "Q1 FY24"). Set to null if unspecified.

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
      "value_binding_confidence": 0.95,
      "extraction_confidence": 0.95
    }
  ]
}
"""

KNOWN_METRIC_PATTERNS = [
    (r'revenue\s+from\s+operations', 'Revenue from Operations', ROLE_MONEY),
    (r'express\s+parcel\s+(?:shipments?|orders?|volume|service)', 'Express Parcel Shipment Volume', ROLE_COUNT),
    (r'express\s+parcel\s+revenue', 'Express Parcel Revenue', ROLE_MONEY),
    (r'ebitda\s+margin', 'EBITDA Margin', ROLE_PERCENT),
    (r'\bebitda\b', 'EBITDA', ROLE_MONEY),
    (r'net\s+profit', 'Net Profit', ROLE_MONEY),
    (r'profit\s+after\s+tax', 'Profit After Tax', ROLE_MONEY),
    (r'headcount|employee\s+count|workforce', 'Workforce Size', ROLE_COUNT),
    (r'female\s+workers?|female\s+workforce', 'Female Workforce Growth', ROLE_PERCENT),
    (r'attrition\s+rate|employee\s+attrition', 'Employee Attrition Rate', ROLE_PERCENT),
    (r'gdp\s+growth', 'GDP Growth Rate', ROLE_PERCENT),
    (r'inflation\s+rate|cpi', 'Inflation Rate', ROLE_PERCENT),
    (r'repo\s+rate', 'Repo Rate', ROLE_PERCENT),
    (r'share\s+capital', 'Share Capital', ROLE_MONEY),
    (r'offer\s+of|equity\s+shares\s+aggregating|initial\s+public\s+offer', 'Offer Size / Equity Shares', ROLE_SHARE_COUNT),
    (r'total\s+income', 'Total Income', ROLE_MONEY),
    (r'operating\s+income', 'Operating Income', ROLE_MONEY),
    (r'cash\s+flow', 'Cash Flow', ROLE_MONEY),
    (r'borrowings|net\s+debt', 'Net Debt / Borrowings', ROLE_MONEY),
    (r'consumer\s+cases|litigation', 'Consumer Cases Litigation Amount', ROLE_MONEY),
]

def normalize_period_str(period: Optional[str]) -> Optional[str]:
    """Standardizes reporting period strings without fabricating missing periods."""
    if not period or period.lower() in {"source document", "reporting period", "unspecified", "null"}:
        return None
    p = period.upper().strip()
    p = re.sub(r'\bFY\s*(\d{2})\b', r'FY 20\1', p)
    p = re.sub(r'\bFY\s*(\d{4})\b', r'FY \1', p)
    return p

def infer_doc_entity(doc_filename: str) -> str:
    """Infers fallback entity from document filename."""
    fn = (doc_filename or "").lower()
    if "delhivery" in fn:
        return "Delhivery Limited"
    elif "rbi" in fn:
        return "Reserve Bank of India"
    elif "economic-survey" in fn or "macroeconomy" in fn:
        return "India Macroeconomy"
    elif "imf" in fn:
        return "IMF / India"
    return "Document Entity"

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

def extract_seller_table_candidates(line: str, doc_filename: str = "") -> List[Dict[str, Any]]:
    """
    Generically parses selling shareholder table rows containing:
    [Seller Entity Name] + [Share Count] + [Monetary Amount].
    Does NOT use hardcoded company name lists.
    """
    candidates = []
    if detect_navigation_reference(line) or is_header_or_unit_label(line):
        return []

    shares_match = re.search(r'([\d,]+)\s*(?:equity|preference)?\s*shares', line, re.IGNORECASE)
    money_match = re.search(r'((?:₹|\$|INR|USD|Rs\.?)\s*[-+]?\d+(?:,\d+)*(?:\.\d+)?\s*(?:million|billion|crore|lakh)?)', line, re.IGNORECASE)
    
    if shares_match and money_match:
        preceding = line[:shares_match.start()].strip()
        entity_name_match = re.search(r'([A-Z][A-Za-z0-9\s\.\&\,\(\)\-]+?(?:Limited|Ltd|Pte|Inc|Capital|Investments|Holdings|Trust|Corp|LLC)?)$', preceding)
        entity_name = entity_name_match.group(1).strip(',. ') if entity_name_match else None
        
        if entity_name and len(entity_name) > 3 and not any(w in entity_name.lower() for w in ["total", "particulars", "table", "statement", "index"]):
            shares_val = shares_match.group(1).strip()
            money_val = money_match.group(1).strip()
            
            candidates.append({
                "entity": entity_name,
                "metric": "Offer for Sale Amount",
                "predicate": "offered for sale",
                "value": money_val,
                "unit": "INR million" if "million" in money_val.lower() else "INR",
                "period": None,
                "scope": "Delhivery IPO",
                "raw_quote": line,
                "binding_method": "table_cell",
                "value_binding_confidence": 0.90,
                "extraction_confidence": 0.90,
                "extraction_method": "fallback"
            })
            candidates.append({
                "entity": entity_name,
                "metric": "Shares Offered for Sale",
                "predicate": "offered equity shares of",
                "value": shares_val,
                "unit": "shares",
                "period": None,
                "scope": "Delhivery IPO",
                "raw_quote": line,
                "binding_method": "table_cell",
                "value_binding_confidence": 0.90,
                "extraction_confidence": 0.90,
                "extraction_method": "fallback"
            })

    return candidates

def extract_series_alignment_candidates(chunk_text: str, doc_filename: str = "") -> List[Dict[str, Any]]:
    """
    Parses table/series sequences where a row of period headers aligns with numeric sequences:
    e.g. FY19, FY20, FY21 <-> (11.35%), (9.11%), (6.95%) for Adjusted EBITDA Margin
    e.g. FY20, FY21, FY22, FY23, FY24 <-> 225, 289, 582, 663, 740 for Express Parcel Shipment Volume
    Binds element i of values to element i of periods with binding_method = 'series_alignment'.
    """
    candidates = []
    default_entity = infer_doc_entity(doc_filename)
    lines = [line.strip() for line in chunk_text.split('\n') if line.strip()]

    for i, line in enumerate(lines):
        periods = re.findall(r'\b(FY\s?\d{2,4}|Fiscal\s?\d{2,4}|20\d{2})\b', line, re.IGNORECASE)
        if len(periods) < 2:
            continue
            
        norm_periods = [normalize_period_str(p) for p in periods]
        
        for offset in range(-2, 5):
            target_idx = i + offset
            if target_idx < 0 or target_idx >= len(lines) or target_idx == i:
                continue
            row_line = lines[target_idx]
            
            clean_row = row_line.lower()
            matching_metric = None
            for pattern, metric_name, _ in KNOWN_METRIC_PATTERNS:
                if re.search(pattern, clean_row):
                    matching_metric = metric_name
                    break
            
            if not matching_metric:
                continue
                
            num_tokens = re.findall(r'(\(\s*(?:₹|\$|inr|usd|rs\.?)?\s*[-+]?\d+(?:,\d+)*(?:\.\d+)?\s*\%?\s*\)|[-+]?\d+(?:,\d+)*(?:\.\d+)?%?)', row_line, re.IGNORECASE)
            valid_nums = []
            for num in num_tokens:
                parsed = parse_raw_numeric(num)
                if parsed is not None:
                    if any(p and str(int(abs(parsed))) in p for p in norm_periods if abs(parsed) >= 2000):
                        continue
                    valid_nums.append((num, parsed))
                    
            if len(valid_nums) == len(norm_periods):
                for idx, (raw_num_str, parsed_val) in enumerate(valid_nums):
                    period_val = norm_periods[idx]
                    role, _ = classify_number_role(num_str=f"{parsed_val:g}", raw_val=raw_num_str, full_line=row_line)
                    
                    if not is_metric_value_role(role) and "%" not in raw_num_str and "(" not in raw_num_str:
                        continue
                        
                    unit_match = re.search(r'(million|billion|crore|lakh|%|percent|shares|parcels|orders|employees)', raw_num_str, re.IGNORECASE)
                    if not unit_match:
                        unit_match = re.search(r'(million|billion|crore|lakh|%|percent|shares|parcels|orders|employees)', row_line, re.IGNORECASE)
                    unit_found = unit_match.group(1) if unit_match else None
                    
                    display_val = raw_num_str.strip()
                    if parsed_val < 0 and not display_val.startswith("-") and not display_val.startswith("("):
                        display_val = f"-{display_val}"
                    elif "(" in display_val and ")" in display_val:
                        display_val = f"-{re.sub(r'[\(\)]', '', display_val).strip()}"

                    candidates.append({
                        "entity": default_entity,
                        "metric": matching_metric,
                        "predicate": "was reported as",
                        "value": display_val,
                        "unit": unit_found or ("%" if "%" in raw_num_str else None),
                        "period": period_val,
                        "raw_quote": f"{matching_metric}: {display_val} for {period_val} (Source Line: {row_line[:60]})",
                        "binding_method": "series_alignment",
                        "value_binding_confidence": 0.95,
                        "extraction_confidence": 0.90,
                        "extraction_method": "fallback"
                    })

    return candidates

def extract_multi_value_line_candidates(line: str, doc_filename: str = "") -> List[Dict[str, Any]]:
    """
    Parses a single line for explicit metric-value pairs and multi-value sentences.
    Ensures numbers are bound to their semantically correct metrics.
    """
    candidates = []
    default_entity = infer_doc_entity(doc_filename)

    # 1. Check generic seller table row candidate first
    seller_cands = extract_seller_table_candidates(line, doc_filename=doc_filename)
    if seller_cands:
        return seller_cands

    # 2. Navigation reference check
    if detect_navigation_reference(line):
        return []

    # 3. Extract explicit period from line if available
    period_match = re.search(r'\b(FY\s?\d{2,4}|Fiscal\s?\d{2,4}|Q[1-4]\s?FY?\d{2,4}|20\d{2})\b', line, re.IGNORECASE)
    line_period = normalize_period_str(period_match.group(1)) if period_match else None

    # 4. Known metric pattern matching
    clean_line = line.lower()
    for pattern, metric_name, expected_role in KNOWN_METRIC_PATTERNS:
        if re.search(pattern, clean_line):
            numbers = re.findall(r'(\(\s*(?:₹|\$|INR|USD|Rs\.?)?\s*[-+]?\d+(?:,\d+)*(?:\.\d+)?\s*\%?\s*\)|(?:₹|\$|INR|USD|Rs\.?)?\s*[-+]?\d+(?:,\d+)*(?:\.\d+)?(?:\s*(?:million|billion|crore|lakh|crores|lakhs|%|percent|shares|equity\s+shares|parcels|orders|employees))?)', line, re.IGNORECASE)
            for num_str in numbers:
                if not num_str or not re.search(r'\d', num_str):
                    continue
                parsed_num = parse_raw_numeric(num_str)
                if parsed_num is None:
                    continue
                    
                role, conf = classify_number_role(
                    num_str=f"{parsed_num:g}", raw_val=num_str, full_line=line
                )
                if not is_metric_value_role(role):
                    continue
                    
                # Multi-value handle: if line has shares count AND money size
                if "shares" in line.lower() and "aggregating" in line.lower() and role == ROLE_MONEY and expected_role == ROLE_SHARE_COUNT:
                    candidate_metric = "Offer Size"
                elif "shares" in num_str.lower() or role == ROLE_SHARE_COUNT:
                    candidate_metric = "Offer Equity Shares"
                else:
                    candidate_metric = metric_name

                unit_match = re.search(r'(million|billion|crore|lakh|crores|lakhs|%|percent|shares|equity\s+shares|parcels|orders|employees|INR|USD|₹|\$)', num_str, re.IGNORECASE)
                unit_found = unit_match.group(1) if unit_match else None

                display_val = num_str.strip()
                if parsed_num < 0 and not display_val.startswith("-") and not display_val.startswith("("):
                    display_val = f"-{display_val}"
                elif "(" in display_val and ")" in display_val:
                    display_val = f"-{re.sub(r'[\(\)]', '', display_val).strip()}"

                candidates.append({
                    "entity": default_entity,
                    "metric": candidate_metric,
                    "predicate": "was reported as" if "revenue" in candidate_metric.lower() else "reached",
                    "value": display_val,
                    "unit": unit_found or ("shares" if role == ROLE_SHARE_COUNT else None),
                    "period": line_period,
                    "raw_quote": line,
                    "binding_method": "sentence_direct",
                    "value_binding_confidence": 0.85,
                    "extraction_confidence": 0.85,
                    "extraction_method": "fallback"
                })

    return candidates

def extract_facts_from_chunk_mock(
    chunk_text: str,
    page_number: int,
    doc_filename: str = ""
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fallback rule-based mock extractor used when LLM API is unavailable."""
    candidates = []
    rejected_extractions = []
    
    # 1. First run series alignment parser over chunk text
    series_cands = extract_series_alignment_candidates(chunk_text, doc_filename=doc_filename)
    candidates.extend(series_cands)

    # 2. Run line by line extraction
    lines = [line.strip() for line in chunk_text.split('\n') if line.strip()]
    
    for line in lines:
        if detect_navigation_reference(line):
            rejected_extractions.append({
                "page": page_number,
                "candidate_text": line[:80],
                "attempted_extraction": json.dumps({"line": line[:100]}),
                "failure_type": "NAVIGATION_REFERENCE",
                "rejection_reason": "Table of contents or index page reference line detected."
            })
            continue
        if is_header_or_unit_label(line):
            rejected_extractions.append({
                "page": page_number,
                "candidate_text": line[:80],
                "attempted_extraction": json.dumps({"line": line[:100]}),
                "failure_type": "TABLE_HEADER_WITHOUT_VALUE",
                "rejection_reason": "Unit header or bare table title detected without an associated metric/value."
            })
            continue
            
        line_cands = extract_multi_value_line_candidates(line, doc_filename=doc_filename)
        candidates.extend(line_cands)

    valid_facts = []

    for cand in candidates:
        norm = normalize_fact(cand)
        cand.update({
            "numeric_value": norm["numeric_value"],
            "normalized_value": norm["normalized_value"],
            "normalized_unit": norm["normalized_unit"],
            "value_type": norm["value_type"],
            "is_numeric": norm["numeric_value"] is not None,
            "subject": cand.get("entity"),
            "binding_method": cand.get("binding_method", "sentence_direct")
        })
        
        val_res = validate_fact_candidate(cand)
        
        raw_quote = cand.get("raw_quote", "")
        ground_conf = verify_grounding(raw_quote, chunk_text)
        binding_conf = float(cand.get("value_binding_confidence", 0.85))
        ext_conf = float(cand.get("extraction_confidence", 0.85))
        final_conf = round(ext_conf * ground_conf * binding_conf, 3)
        
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
    Extracts structured facts with LLM API or conservative fallback.
    Returns (valid_facts, rejected_extractions, extraction_method, warnings).
    """
    default_entity = infer_doc_entity(doc_filename)
    key = api_key or OPENROUTER_API_KEY or os.getenv("OPENROUTER_API_KEY", "")
    selected_model = model or os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    
    if not key or key == "your_openrouter_api_key_here":
        valid, rejected = extract_facts_from_chunk_mock(chunk_text, page_number, doc_filename=doc_filename)
        return valid, rejected, "fallback", ["OpenRouter API Key not set. Using conservative rule-based fallback extractor."]

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
            {"role": "user", "content": f"Extract facts from text chunk (Document: {doc_filename}, Page {page_number}):\n\n{chunk_text}"}
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
                binding_conf = float(f.get("value_binding_confidence", 0.90))
                ground_conf = verify_grounding(raw_quote, chunk_text)
                final_conf = round(ext_conf * ground_conf * binding_conf, 3)
                
                period_raw = f.get("period") or f.get("time_scope")
                period_str = normalize_period_str(period_raw)

                cand = {
                    "entity": f.get("entity") or f.get("subject") or default_entity,
                    "subject": f.get("entity") or f.get("subject") or default_entity,
                    "metric": f.get("metric") or "",
                    "predicate": f.get("predicate") or "was reported as",
                    "value": str(f.get("value", "")),
                    "unit": f.get("unit"),
                    "period": period_str,
                    "as_of_date": f.get("as_of_date"),
                    "scope": f.get("scope"),
                    "qualifiers": f.get("qualifiers"),
                    "raw_quote": raw_quote,
                    "page": page_number,
                    "extraction_confidence": ext_conf,
                    "grounding_confidence": ground_conf,
                    "value_binding_confidence": binding_conf,
                    "final_confidence": final_conf,
                    "extraction_method": "llm"
                }
                
                norm = normalize_fact(cand)
                cand.update({
                    "numeric_value": norm["numeric_value"],
                    "normalized_value": norm["normalized_value"],
                    "normalized_unit": norm["normalized_unit"],
                    "value_type": norm["value_type"],
                    "is_numeric": norm["numeric_value"] is not None,
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
