import re
from typing import Dict, Any, List, Tuple, Optional

# Roles
ROLE_MONEY = "MONEY"
ROLE_PERCENT = "PERCENT"
ROLE_SHARE_COUNT = "SHARE_COUNT"
ROLE_COUNT = "COUNT"
ROLE_QUANTITY = "QUANTITY"
ROLE_YEAR = "YEAR"
ROLE_DATE_COMPONENT = "DATE_COMPONENT"
ROLE_PAGE_REFERENCE = "PAGE_REFERENCE"
ROLE_NOTE_REFERENCE = "NOTE_REFERENCE"
ROLE_LIST_INDEX = "LIST_INDEX"
ROLE_UNKNOWN = "UNKNOWN"

METRIC_VALUE_ROLES = {ROLE_MONEY, ROLE_PERCENT, ROLE_SHARE_COUNT, ROLE_COUNT, ROLE_QUANTITY}

def detect_navigation_reference(line: str) -> bool:
    """
    Detects table of contents / index dot-leader page reference lines like:
    'CAPITAL STRUCTURE .............................. 117'
    'FINANCIAL INDEBTEDNESS ........ 513'
    """
    if not line:
        return False
    clean = line.strip()
    # Check dot leader pattern: text + 2 or more dots (with optional spaces) + page number at end
    if re.search(r'(?:\.\s*|\u2026\s*){2,}\d+\s*$', clean):
        return True
    if re.search(r'\.{2,}\s*\d+', clean):
        return True
    # Check page reference pattern: 'page 544' or 'p. 117' as line or fragment
    if re.search(r'\b(?:page|p\.?)\s*\d+\b', clean, re.IGNORECASE):
        return True
    return False

def classify_number_role(
    num_str: str,
    raw_val: str = "",
    unit_str: str = "",
    preceding_text: str = "",
    following_text: str = "",
    full_line: str = ""
) -> Tuple[str, float]:
    """
    Classifies a numeric token into its semantic role and returns (role, binding_confidence).
    """
    combined = f"{preceding_text} {raw_val} {unit_str} {following_text} {full_line}".lower()
    val_unit = f"{raw_val} {unit_str}".lower()
    
    # 1. Page reference check
    if detect_navigation_reference(full_line):
        return ROLE_PAGE_REFERENCE, 0.95
    if re.search(r'\b(?:page|p\.?)\s*' + re.escape(num_str) + r'\b', combined):
        return ROLE_PAGE_REFERENCE, 0.95

    # 2. Note reference check
    if re.search(r'\b(?:note|footnote)\s*' + re.escape(num_str) + r'\b', combined):
        return ROLE_NOTE_REFERENCE, 0.95

    # 3. Year check (4-digit years like 2024 or 2-digit years like FY24)
    if re.match(r'^(?:19|20)\d{2}$', num_str):
        # Check if preceded by month or date words like 'march 31, 2024' or 'fy2024'
        if re.search(r'\b(?:fy|fiscal|quarter|q[1-4]|year|ended|as at|march|december|june|september)\b', combined):
            return ROLE_YEAR, 0.95
        # Standalone 4-digit year
        if not re.search(r'(?:₹|\$|inr|usd|rs|percent|\%|shares|parcels|employees)', val_unit):
            return ROLE_YEAR, 0.90
    elif re.match(r'^\d{2}$', num_str) and re.search(r'\b(?:fy|fiscal|q[1-4]\s*fy|20)\s*' + re.escape(num_str) + r'\b', combined):
        return ROLE_YEAR, 0.95

    # 4. Date Component check (e.g., '31' in 'March 31, 2024' or '9' in '9 months ended')
    if re.search(r'\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+' + re.escape(num_str) + r'\b', combined):
        return ROLE_DATE_COMPONENT, 0.95
    if re.search(r'\b' + re.escape(num_str) + r'\s+(?:months?|days?)\s+ended\b', combined):
        return ROLE_DATE_COMPONENT, 0.95

    # 5. Share Count check
    if re.search(r'\b(?:shares?|equity shares?|preference shares?|securities)\b', val_unit):
        return ROLE_SHARE_COUNT, 0.95
    if re.search(r'\b' + re.escape(num_str) + r'\s+(?:equity|preference)?\s*shares?\b', combined):
        return ROLE_SHARE_COUNT, 0.90

    # 6. Money check
    if any(sym in val_unit for sym in ["₹", "$", "inr", "usd", "rs", "rs.", "rupees", "dollars"]):
        return ROLE_MONEY, 0.95
    if re.search(r'(?:₹|\$|inr|usd|rs\.?)\s*(?:\w+\s+){0,2}' + re.escape(num_str), combined):
        return ROLE_MONEY, 0.90

    # 7. Percentage check
    if "%" in val_unit or "percent" in val_unit or "percentage" in val_unit:
        return ROLE_PERCENT, 0.95
    if re.search(r'\b' + re.escape(num_str) + r'\s*(?:\%|percent|percentage)\b', combined):
        return ROLE_PERCENT, 0.90

    # 8. Quantity / Count check (Parcels, Employees, Orders, Facilities, Hubs)
    if re.search(r'\b(?:parcels?|orders?|shipments?|employees?|headcount|workers?|facilities|hubs|vehicles|centres)\b', combined):
        return ROLE_COUNT, 0.90

    # 9. List Index check
    if re.match(r'^\(?\d+[\)\.]?$', raw_val.strip()) and len(full_line.strip()) > 20:
        if full_line.strip().startswith(raw_val.strip()):
            return ROLE_LIST_INDEX, 0.85

    return ROLE_UNKNOWN, 0.50

def is_metric_value_role(role: str) -> bool:
    """Returns True ONLY for roles that legitimately populate a metric value."""
    return role in METRIC_VALUE_ROLES
