import re
from typing import Dict, Any, List, Tuple

from app.number_classifier import (
    detect_navigation_reference, classify_number_role, is_metric_value_role,
    is_section_prefix_number, ROLE_PAGE_REFERENCE, ROLE_YEAR, ROLE_DATE_COMPONENT, ROLE_NOTE_REFERENCE, ROLE_LIST_INDEX
)

HEADER_PATTERNS = [
    r'^\(?\s*(?:₹|rs\.?|inr|usd|\$)?\s*(?:in\s+)?(?:₹\s+)?(?:million|crore|lakh|billion|thousands?|mn|bn)\s*\)?$',
    r'^\(?\s*in\s*₹?\s*(?:million|crore|lakh|billion|mn|bn)\s*\)?$',
    r'^\(?\s*₹?\s*in\s*(?:million|crore|lakh|billion|mn|bn)\s*\)?$',
    r'^particulars$',
    r'^statement\s+of\s+.*$',
    r'^fy\d{2}(?:\s+fy\d{2})+$',
    r'^(?:million|billion|crore|lakh|thousand|\%|₹|\$)$',
    r'^.*book\s+built\s+offer.*$',
    r'^.*exchange\s+board\s+of\s+india.*$',
    r'^.*issue\s+of\s+capital.*$',
    r'^.*tax\s+benefits.*$'
]

UNIT_KEYWORDS = {
    "million", "crore", "lakh", "billion", "thousand", "mn", "bn", "cr", "lacs", "lac",
    "inr", "usd", "%", "percent", "percentage", "rupees", "dollars", "rs", "₹", "$"
}

GENERIC_METRICS = {
    "general metric", "general assertion", "table header", "table unit header",
    "particulars", "unknown metric", "statement", "document claim", "note", "amount",
    "value", "item", "total", "subtotal", "figure", "exchange board of india",
    "book built offer", "issue of capital and disclosure requirements", "draft red herring prospectus",
    "special tax benefits", "inter-se allocation of responsibilities", "equity shares aggregating"
}

GENERIC_SUBJECTS = {
    "document claim", "document assertion", "table header", "statement", 
    "particulars", "note", "unknown subject", "unknown entity", "general assertion"
}

GENERIC_PREDICATES = {
    "states", "shows", "has", "is", "reported", "contains"
}

def is_header_or_unit_label(text: str) -> bool:
    """Checks if text is merely a table header, unit label, column title, or prospectus header."""
    if not text:
        return False
    clean = text.strip().lower()
    if clean in UNIT_KEYWORDS or clean in GENERIC_METRICS or clean.startswith("#"):
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
    unit = str(fact.get("unit") or "").strip()
    binding_conf = float(fact.get("value_binding_confidence", 1.0))

    # 1. Navigation Reference / Table of Contents Page Reference Check (Task 6 & Task 1)
    if detect_navigation_reference(quote) or detect_navigation_reference(value):
        return {
            "valid": False,
            "failure_type": "NAVIGATION_REFERENCE",
            "rejection_reason": f"Table of contents or index page reference line detected ('{quote[:40]}...').",
            "warnings": ["TOC Page Reference"]
        }

    # 2. Evidence Quote Presence Check
    if not quote or len(quote) < 4:
        return {
            "valid": False,
            "failure_type": "INSUFFICIENT_CONTEXT",
            "rejection_reason": "Fact lacks valid supporting evidence quote.",
            "warnings": ["Missing raw quote"]
        }

    # 3. Number Role Typing Check (Task 2)
    if num_val is not None:
        role, conf = classify_number_role(
            num_str=f"{num_val:g}", raw_val=value, unit_str=unit, full_line=quote
        )
        if not is_metric_value_role(role):
            return {
                "valid": False,
                "failure_type": "INVALID_NUMBER_ROLE",
                "rejection_reason": f"Number '{value}' represents a {role} rather than a metric value.",
                "warnings": [f"Number classified as {role}"]
            }

        # 3.1 Hard-reject section/paragraph numbers as values
        clean_quote = quote.strip()
        if is_section_prefix_number(clean_quote, str(value).strip(), num_val):
            return {
                "valid": False,
                "failure_type": "SECTION_IDENTIFIER_AS_VALUE",
                "rejection_reason": f"Number '{value}' is a section/paragraph identifier prefix, not a metric value.",
                "warnings": ["Section prefix number rejected"]
            }

        # 3.2 Hard-reject basis point changes and spreads masquerading as base rate level
        metric_lower = metric.lower()
        if ("bps" in quote.lower() or role in {"BASIS_POINT_CHANGE", "SPREAD"}) and ("repo" in metric_lower or "interest" in metric_lower or "rate" in metric_lower):
            if not ("change" in metric_lower or "spread" in metric_lower or "delta" in metric_lower):
                return {
                    "valid": False,
                    "failure_type": "DELTA_SPREAD_AS_LEVEL",
                    "rejection_reason": f"Quantity '{value}' represents a rate change or spread, but fact asserts policy rate level ('{metric}').",
                    "warnings": ["Rate change/spread mismatch with level metric"]
                }

        # 3.3 Unit Dimension Enforcement: Known metrics MUST possess corresponding units
        unit_lower = (unit or "").lower().strip()
        if any(k in metric_lower for k in ["inflation", "gdp", "growth rate", "repo rate"]):
            if not ("change" in metric_lower or "spread" in metric_lower or "delta" in metric_lower):
                if unit_lower != "%" and "percent" not in unit_lower and "bps" not in unit_lower and "%" not in str(value):
                    return {
                        "valid": False,
                        "failure_type": "MISSING_PERCENT_UNIT",
                        "rejection_reason": f"Metric '{metric}' is a percentage rate, but unit is '{unit or 'None'}' (must have % or bps).",
                        "warnings": ["Rate metric missing percentage unit"]
                    }

        if any(k in metric_lower for k in ["borrowings", "net debt", "revenue", "income", "cash flow", "offer size", "share capital", "litigation"]):
            if not any(c in unit_lower or c in str(value).lower() for c in ["inr", "usd", "₹", "$", "rs", "crore", "million", "billion", "lakh"]):
                return {
                    "valid": False,
                    "failure_type": "MISSING_CURRENCY_UNIT",
                    "rejection_reason": f"Monetary metric '{metric}' requires currency or monetary scale unit, but got '{unit or 'None'}'.",
                    "warnings": ["Monetary metric missing currency unit"]
                }

    # 4. Value Binding Confidence Check (Task 1)
    if num_val is not None and binding_conf < 0.75:
        return {
            "valid": False,
            "failure_type": "LOW_BINDING_CONFIDENCE",
            "rejection_reason": f"Metric-value binding confidence ({binding_conf:.2f}) is below threshold 0.75.",
            "warnings": ["Low value binding confidence"]
        }

    # 5. Bare table header / unit label check
    if is_header_or_unit_label(value) or is_header_or_unit_label(metric):
        return {
            "valid": False,
            "failure_type": "TABLE_HEADER_WITHOUT_VALUE",
            "rejection_reason": f"Detected a table header or regulatory title ('{metric or value}') without associated metric quantity.",
            "warnings": ["Bare table header or unit label"]
        }

    # 6. Generic metric check (General Metric, Table Header, Particulars, etc.)
    clean_metric = metric.lower().strip()
    if not clean_metric or clean_metric in GENERIC_METRICS or clean_metric in UNIT_KEYWORDS or clean_metric.startswith("#"):
        return {
            "valid": False,
            "failure_type": "VALUE_WITHOUT_METRIC",
            "rejection_reason": f"Fact candidate metric is generic or regulatory title ('{metric}') without specific financial/operational metric context.",
            "warnings": ["Generic or missing metric name"]
        }

    # 7. Non-numeric semantic noise filter (Task 8)
    if num_val is None:
        val_clean = value.lower().strip()
        if len(val_clean) < 5 or val_clean in {"through profit or loss", "see note", "n/a", "nil", "none", "refer note"}:
            return {
                "valid": False,
                "failure_type": "INSUFFICIENT_CONTEXT",
                "rejection_reason": f"Non-numeric claim '{value}' lacks discrete factual assertion.",
                "warnings": ["Generic non-numeric phrase"]
            }

    # 8. Extraction confidence check
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
