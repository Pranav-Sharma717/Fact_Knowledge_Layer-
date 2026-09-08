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

UNIT_KEYWORDS = {
    "million", "crore", "lakh", "billion", "thousand", "mn", "bn", "cr", "lacs", "lac",
    "inr", "usd", "%", "percent", "percentage", "rupees", "dollars", "rs", "₹", "$"
}

GENERIC_METRICS = {
    "general metric", "general assertion", "table header", "table unit header",
    "particulars", "unknown metric", "statement", "document claim", "note", "amount",
    "value", "item", "total", "subtotal", "figure"
}

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
    if clean in UNIT_KEYWORDS or clean in GENERIC_METRICS:
        return True
    for pattern in HEADER_PATTERNS:
        if re.match(pattern, clean):
            return True
    return False

def validate_fact_candidate(fact: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates an extracted fact candidate against strict quality guidelines.
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
    num_val = fact.get("numeric_value")
    
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
        
    # 3. Bare unit in value or metric
    if value.lower() in UNIT_KEYWORDS or metric.lower() in UNIT_KEYWORDS:
        return {
            "valid": False,
            "failure_type": "TABLE_HEADER_WITHOUT_VALUE",
            "rejection_reason": f"Metric or value contains only unit keyword '{metric or value}' without metric quantity.",
            "warnings": ["Unit keyword as metric/value"]
        }

    # 4. Generic metric check (General Metric, Table Header, Particulars, etc.)
    clean_metric = metric.lower().strip()
    if not clean_metric or clean_metric in GENERIC_METRICS or clean_metric in UNIT_KEYWORDS:
        return {
            "valid": False,
            "failure_type": "VALUE_WITHOUT_METRIC",
            "rejection_reason": f"Fact candidate metric is generic or invalid ('{metric}') without specific financial/operational metric context.",
            "warnings": ["Generic or missing metric name"]
        }

    # 5. Non-numeric semantic noise filter
    if num_val is None:
        # Check if value is just generic accounting prose without clear claim
        val_clean = value.lower().strip()
        if len(val_clean) < 5 or val_clean in {"through profit or loss", "see note", "n/a", "nil", "none", "refer note"}:
            return {
                "valid": False,
                "failure_type": "INSUFFICIENT_CONTEXT",
                "rejection_reason": f"Non-numeric claim '{value}' lacks discrete factual assertion.",
                "warnings": ["Generic non-numeric phrase"]
            }

    # 6. Generic subject and generic predicate without specific metric
    is_subject_generic = subject.lower() in GENERIC_SUBJECTS or not subject
    is_pred_generic = predicate.lower() in GENERIC_PREDICATES or not predicate
    
    if is_subject_generic and is_pred_generic and clean_metric in GENERIC_METRICS:
        return {
            "valid": False,
            "failure_type": "VALUE_WITHOUT_METRIC",
            "rejection_reason": "Subject and predicate are generic ('Document Claim / states') and no specific metric could be inferred.",
            "warnings": ["Generic subject and predicate"]
        }

    # 7. Low extraction confidence
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
