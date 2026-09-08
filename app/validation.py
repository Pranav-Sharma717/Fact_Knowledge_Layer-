import re
from typing import Dict, Any, List, Tuple

HEADER_PATTERNS = [
    r'^\(?\s*(?:₹|rs\.?|inr|usd|\$)?\s*(?:in\s+)?(?:million|crore|lakh|billion|thousands?|mn|bn)\s*\)?$',
    r'^\(?\s*in\s+(?:million|crore|lakh|billion|mn|bn)\s*\)?$',
    r'^particulars$',
    r'^statement\s+of\s+.*$',
    r'^fy\d{2}(?:\s+fy\d{2})+$',
    r'^\(?\s*₹\s*in\s+million\s*\)?$',
    r'^\(?\s*rs\.?\s*in\s+million\s*\)?$',
    r'^(?:million|billion|crore|lakh|thousand|\%|₹|\$)$'
]

GENERIC_SUBJECTS = {
    "document claim", "document assertion", "table header", "statement", 
    "particulars", "note", "unknown subject", "unknown entity", "general assertion"
}

GENERIC_PREDICATES = {
    "states", "shows", "has", "is", "reported", "contains"
}

def is_header_or_unit_label(text: str) -> bool:
    """Checks if text is merely a table header, unit label, or column title."""
    if not text:
        return True
    clean = text.strip().lower()
    for pattern in HEADER_PATTERNS:
        if re.match(pattern, clean):
            return True
    return False

def validate_fact_candidate(fact: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates an extracted fact candidate.
    Returns dict:
      - valid: bool
      - failure_type: Optional[str]
      - rejection_reason: Optional[str]
      - warnings: List[str]
    """
    warnings = []
    
    subject = str(fact.get("subject") or fact.get("entity") or "").strip()
    metric = str(fact.get("metric") or "").strip()
    predicate = str(fact.get("predicate") or "").strip()
    value = str(fact.get("value") or "").strip()
    quote = str(fact.get("raw_quote") or "").strip()
    unit = str(fact.get("unit") or "").strip()
    
    # 1. No evidence / quote check
    if not quote or len(quote) < 4:
        return {
            "valid": False,
            "failure_type": "INSUFFICIENT_CONTEXT",
            "rejection_reason": "Fact lacks valid supporting evidence quote.",
            "warnings": ["Missing raw quote"]
        }
        
    # 2. Bare table header / unit label check in value or quote
    if is_header_or_unit_label(value) or is_header_or_unit_label(quote):
        return {
            "valid": False,
            "failure_type": "TABLE_HEADER_WITHOUT_VALUE",
            "rejection_reason": f"Detected a table-wide unit label or header ('{value or quote}') without associated entity or metric.",
            "warnings": ["Bare table header or unit label"]
        }
        
    # 3. Bare unit in value
    if value.lower() in {"million", "crore", "lakh", "billion", "%", "inr", "usd", "₹", "$"}:
        return {
            "valid": False,
            "failure_type": "TABLE_HEADER_WITHOUT_VALUE",
            "rejection_reason": f"Value contains only unit keyword '{value}' without metric or quantity.",
            "warnings": ["Unit keyword as value"]
        }

    # 4. Generic subject and generic predicate without specific metric
    is_subject_generic = subject.lower() in GENERIC_SUBJECTS or not subject
    is_pred_generic = predicate.lower() in GENERIC_PREDICATES or not predicate
    
    if is_subject_generic and (is_pred_generic and not metric):
        return {
            "valid": False,
            "failure_type": "VALUE_WITHOUT_METRIC",
            "rejection_reason": "Subject and predicate are generic ('Document Claim / states') and no specific metric could be inferred.",
            "warnings": ["Generic subject and predicate"]
        }

    # 5. Numeric fact lacking context (e.g. bare "0.00%" or isolated number without entity/metric)
    val_num_match = re.search(r'[-+]?\d+(?:\.\d+)?', value)
    if val_num_match:
        # It has a number
        if is_subject_generic and not metric:
            return {
                "valid": False,
                "failure_type": "INSUFFICIENT_CONTEXT",
                "rejection_reason": f"Numeric value '{value}' lacks sufficient entity or metric context.",
                "warnings": ["Numeric value without context"]
            }
            
    # 6. Low extraction confidence
    conf = float(fact.get("extraction_confidence", 1.0))
    if conf < 0.35:
        return {
            "valid": False,
            "failure_type": "LOW_CONFIDENCE",
            "rejection_reason": f"Extraction confidence ({conf:.2f}) is below threshold 0.35.",
            "warnings": ["Low confidence score"]
        }
        
    return {
        "valid": True,
        "failure_type": None,
        "rejection_reason": None,
        "warnings": warnings
    }
