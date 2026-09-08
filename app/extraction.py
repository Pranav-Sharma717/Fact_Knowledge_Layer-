import os
import json
import httpx
import re
from typing import List, Dict, Any, Tuple
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are an expert fact-extraction engine for an intelligence system.
Your job is to read a document chunk and extract all discrete, atomic facts present in the text.

Guidelines:
1. Do NOT use fixed or hardcoded predicate/subject categories. Let the subject and predicate vocabularies emerge naturally from the text.
2. Every fact must be atomic, precise, and standalone.
3. Grounding is CRITICAL: You MUST supply a 'raw_quote' field that contains the EXACT VERBATIM substring from the provided chunk text supporting the fact.
4. Schema for each fact:
   - "subject": Entity or topic being described (e.g. "ACME Corp 2023 revenue", "Workforce size")
   - "predicate": The property, action, or relation (e.g. "total revenue was", "expanded to", "capped at")
   - "value": The extracted numeric or categorical value/claim (e.g. "$5.2 million", "120", "15%")
   - "unit": Unit of measurement if applicable (e.g. "USD", "employees", "percent"), or null if none
   - "time_scope": Time period or scope if specified (e.g. "FY 2023", "Q1 2024", "2024"), or null if none
   - "raw_quote": Exact verbatim quote copied from the text chunk supporting this claim
   - "extraction_confidence": A float between 0.0 and 1.0 reflecting how clearly/unambiguously the fact is stated.

Respond strictly with valid JSON with the format:
{
  "facts": [
    {
      "subject": "...",
      "predicate": "...",
      "value": "...",
      "unit": "...",
      "time_scope": "...",
      "raw_quote": "...",
      "extraction_confidence": 0.95
    }
  ]
}
"""

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

def extract_facts_from_chunk_mock(chunk_text: str, page_number: int) -> List[Dict[str, Any]]:
    """Fallback rule-based mock extractor used when LLM API is unavailable."""
    facts = []
    lines = [line.strip() for line in chunk_text.split('\n') if line.strip()]
    for line in lines:
        if any(kw in line.lower() for kw in ["revenue", "$", "%", "employees", "crore", "billion", "million", "growth", "headcount", "profit", "expenditure"]):
            facts.append({
                "subject": "Document Claim",
                "predicate": "states",
                "value": line,
                "unit": None,
                "time_scope": "Source Document",
                "raw_quote": line,
                "page": page_number,
                "extraction_confidence": 0.85,
                "grounding_confidence": 1.0,
                "final_confidence": 0.85
            })
    return facts

def extract_facts_from_chunk(chunk_text: str, page_number: int, api_key: str = None, model: str = None) -> List[Dict[str, Any]]:
    """Calls OpenRouter API to extract structured facts with automatic graceful fallback."""
    key = api_key or OPENROUTER_API_KEY or os.getenv("OPENROUTER_API_KEY", "")
    selected_model = model or os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    
    if not key or key == "your_openrouter_api_key_here":
        return extract_facts_from_chunk_mock(chunk_text, page_number)
        
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
            {"role": "user", "content": f"Extract facts from the following text chunk (Page {page_number}):\n\n{chunk_text}"}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }
    
    try:
        with httpx.Client(timeout=15.0) as client:
            res = client.post(OPENROUTER_URL, headers=headers, json=payload)
            if res.status_code != 200:
                return extract_facts_from_chunk_mock(chunk_text, page_number)
                
            data = res.json()
            raw_content = data["choices"][0]["message"]["content"]
            parsed = json.loads(raw_content)
            extracted_facts = parsed.get("facts", [])
            
            processed_facts = []
            for f in extracted_facts:
                raw_quote = f.get("raw_quote", "")
                ext_conf = float(f.get("extraction_confidence", 0.9))
                ground_conf = verify_grounding(raw_quote, chunk_text)
                final_conf = round(ext_conf * ground_conf, 3)
                
                processed_facts.append({
                    "subject": f.get("subject", "Document Assertion"),
                    "predicate": f.get("predicate", "states"),
                    "value": str(f.get("value", "")),
                    "unit": f.get("unit"),
                    "time_scope": f.get("time_scope"),
                    "raw_quote": raw_quote,
                    "page": page_number,
                    "extraction_confidence": ext_conf,
                    "grounding_confidence": ground_conf,
                    "final_confidence": final_conf
                })
            return processed_facts
    except Exception:
        return extract_facts_from_chunk_mock(chunk_text, page_number)
