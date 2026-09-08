import re
from typing import Dict, Any, List, Tuple, Optional

# Roles
ROLE_MONEY = "MONEY"
ROLE_PERCENT = "PERCENT"
ROLE_SHARE_COUNT = "SHARE_COUNT"
ROLE_COUNT = "COUNT"
ROLE_QUANTITY = "QUANTITY"
ROLE_METRIC_VALUE = "METRIC_VALUE"
ROLE_METRIC_LEVEL = "METRIC_LEVEL"
ROLE_METRIC_CHANGE = "METRIC_CHANGE"
ROLE_BASIS_POINT_CHANGE = "BASIS_POINT_CHANGE"
ROLE_SPREAD = "SPREAD"
ROLE_PERCENTAGE_POINT_CHANGE = "PERCENTAGE_POINT_CHANGE"
ROLE_GROWTH_RATE = "GROWTH_RATE"
ROLE_ABSOLUTE_VALUE = "ABSOLUTE_VALUE"
ROLE_PARAGRAPH_IDENTIFIER = "PARAGRAPH_IDENTIFIER"
ROLE_CHART_AXIS_TICK = "CHART_AXIS_TICK"

ROLE_FOOTNOTE_REFERENCE = "FOOTNOTE_REFERENCE"
ROLE_SECTION_IDENTIFIER = "SECTION_IDENTIFIER"
ROLE_ROW_IDENTIFIER = "ROW_IDENTIFIER"
ROLE_COLUMN_IDENTIFIER = "COLUMN_IDENTIFIER"
ROLE_TABLE_SEQUENCE_NUMBER = "TABLE_SEQUENCE_NUMBER"
ROLE_PAGE_REFERENCE = "PAGE_REFERENCE"
ROLE_NOTE_REFERENCE = "NOTE_REFERENCE"
ROLE_YEAR = "YEAR"
ROLE_DATE_COMPONENT = "DATE_COMPONENT"
ROLE_REPORTING_PERIOD = "REPORTING_PERIOD"
ROLE_INDEX_BASE_YEAR = "INDEX_BASE_YEAR"
ROLE_INDEX_BASE_VALUE = "INDEX_BASE_VALUE"
ROLE_UNKNOWN = "UNKNOWN"

# Kept as a compatibility alias for callers from the previous pipeline.  A
# numbered list item is structural metadata, never a business value.
ROLE_LIST_INDEX = ROLE_ROW_IDENTIFIER

METRIC_VALUE_ROLES = {ROLE_MONEY, ROLE_PERCENT, ROLE_SHARE_COUNT, ROLE_COUNT, ROLE_QUANTITY, ROLE_METRIC_VALUE, ROLE_METRIC_LEVEL, ROLE_METRIC_CHANGE, ROLE_BASIS_POINT_CHANGE, ROLE_SPREAD, ROLE_PERCENTAGE_POINT_CHANGE, ROLE_GROWTH_RATE, ROLE_ABSOLUTE_VALUE}
STRUCTURAL_ROLES = {
    ROLE_FOOTNOTE_REFERENCE, ROLE_SECTION_IDENTIFIER, ROLE_ROW_IDENTIFIER,
    ROLE_COLUMN_IDENTIFIER, ROLE_TABLE_SEQUENCE_NUMBER, ROLE_PAGE_REFERENCE,
    ROLE_NOTE_REFERENCE, ROLE_YEAR, ROLE_DATE_COMPONENT, ROLE_REPORTING_PERIOD,
    ROLE_INDEX_BASE_YEAR, ROLE_INDEX_BASE_VALUE, ROLE_PARAGRAPH_IDENTIFIER, ROLE_CHART_AXIS_TICK
}

def detect_index_base_metadata(text: str) -> Optional[Dict[str, int]]:
    """
    Detects index base metadata like [2001=100] or 2012=100 or 2016=100 or (2012=100).
    Returns {'index_base_year': 2001, 'index_base_value': 100} or None.
    """
    if not text:
        return None
    match = re.search(r'(?:[\[\(]|\b)(?:FY\s*)?(\d{4})(?:-\d{2,4})?\s*=\s*(\d+)(?:[\]\)]|\b)', text, re.IGNORECASE)
    if match:
        try:
            return {
                "index_base_year": int(match.group(1)),
                "index_base_value": int(match.group(2))
            }
        except ValueError:
            pass
    return None

def is_section_prefix_number(full_line: str, val_str: str, num_val: Any = None) -> bool:
    clean = (full_line or "").strip().lower()
    if not clean:
        return False
    # Check Table/Chart/Figure/Appendix header numbers: e.g. "Chart IV.7:", "APPENDIX TABLE 4:", "Table 1.1"
    tbl_m = re.match(r'^\s*(?:appendix\s+table|table|chart|figure|box)\s+([a-z0-9\.\-]+)', clean)
    if tbl_m:
        prefix_token = tbl_m.group(1).strip()
        if str(val_str).strip() == prefix_token or (num_val is not None and str(num_val).strip() == prefix_token):
            return True
        # If val_str is any single token in the chart/table title like '4' in 'APPENDIX TABLE 4'
        if str(val_str).strip() in prefix_token.split("."):
            return True

    # Decimal section/paragraph or outline prefixes: e.g. "1.12", "1.52", "II.5.10", "3B.1.1"
    m = re.match(r'^\s*\(?((?:[a-z0-9]+\.)+[a-z0-9]+|[0-9]+[a-z]\.[0-9]+|[ivxlcdm]+(?:\.[0-9]+)+)\)?\s+([a-z%])', clean)
    if not m:
        return False
    after_prefix = clean[m.end(1):].strip()
    if re.match(r'^(?:per cent|percent|%|bps|basis\s+points|crore|million|billion|lakh|shares)', after_prefix):
        return False
    prefix_clean = m.group(1).lstrip("abcdefghijklmnopqrstuvwxyz.").strip()
    # Check if val_str matches the entire prefix or its leading integer
    lead_int = re.match(r'^\d+', prefix_clean)
    if lead_int and (str(val_str).strip() == lead_int.group(0) or (num_val is not None and str(num_val).strip() == lead_int.group(0))):
        return True
    return str(val_str).strip() == prefix_clean or (num_val is not None and str(num_val).strip() == prefix_clean)

def detect_navigation_reference(line: str) -> bool:
    if not line:
        return False
    clean = line.strip()
    if re.search(r'(?:\.\s*|\u2026\s*){2,}\d+\s*$', clean):
        return True
    if re.search(r'\.{2,}\s*\d+', clean):
        return True
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
    Classifies a numeric token into its semantic role.
    STRUCTURAL / DOCUMENT METADATA MUST be evaluated BEFORE BUSINESS METRIC VALUE.
    """
    num_clean = num_str.strip()
    raw_clean = raw_val.strip()
    line_clean = full_line.strip()
    combined = f"{preceding_text} {raw_val} {unit_str} {following_text} {full_line}".lower()
    val_unit = f"{raw_val} {unit_str}".lower()

    # 0. Decimal chapter/paragraph/section prefixes must win over any metric keyword:
    # "1.12 Inflation rates across economies", "1.52 Retail headline inflation", "II.5.10 Financial stability", "3B.1.1"
    if is_section_prefix_number(line_clean, num_clean, None):
        return ROLE_PARAGRAPH_IDENTIFIER, 0.99

    # 0.1 Chart axis ticks or isolated negative series ticks like -24, -25, -26 on standalone lines
    if re.match(r'^[-+]?\d{1,3}$', num_clean) and re.match(r'^[-+]?\d{1,3}$', line_clean):
        return ROLE_CHART_AXIS_TICK, 0.99

    # 0.2 Monetary-policy relational quantities are deltas/spreads, not the level.
    if re.search(r'\b(?:bps?|basis\s+points?)\b', combined):
        if re.search(r'\b(?:above|below)\b', combined):
            return ROLE_SPREAD, 0.99
        if re.search(r'\b(?:reduced|decreased|cut|lowered|increased|raised|hiked|change(?:d)?|movement)\s+(?:by\s+)?\b', combined) or re.search(r'\bby\s+' + re.escape(num_clean) + r'\s*(?:bps?|basis\s+points?)\b', combined):
            return ROLE_BASIS_POINT_CHANGE, 0.99

    # 0.3 Percentage point change vs percentage level
    if re.search(r'\b(?:percentage\s+points?|pp)\b', combined):
        return ROLE_PERCENTAGE_POINT_CHANGE, 0.99

    # 0.4 Attached footnote marker directly after word or closing parenthesis: e.g. "(GDP)3", "inflation14"
    if re.search(r'(?:[A-Za-z]|\))' + re.escape(num_clean) + r'(?:\s|$|[,\.;\)])', full_line) and not raw_clean.startswith(("$", "₹", "INR", "USD", "Rs")):
        return ROLE_FOOTNOTE_REFERENCE, 0.98

    # 1. Footnote Reference Check:
    # e.g. "74 Offering collateral-free..." at start of line/paragraph without currency/units
    if re.match(r'^\d{1,3}$', num_clean):
        if line_clean.startswith(num_clean) and re.match(r'^' + re.escape(num_clean) + r'\s+[A-Za-z]', line_clean):
            if not any(kw in val_unit for kw in ["₹", "$", "inr", "usd", "%", "percent", "crore", "million", "shares", "parcels"]):
                return ROLE_FOOTNOTE_REFERENCE, 0.98

    # 2. Section / Row Identifier Check:
    # e.g. "2. CPI-Industrial Workers" or "II.2" or "1. Revenue..." or "2. "
    if re.match(r'^\d{1,2}$', num_clean):
        if re.match(r'^\(?\d{1,2}[\.\)]\s+[A-Za-z]', line_clean):
            if line_clean.startswith(num_clean) or line_clean.startswith(f"{num_clean}.") or line_clean.startswith(f"({num_clean})"):
                return ROLE_ROW_IDENTIFIER, 0.98

    # 3. Index Base Year / Value Check:
    # e.g. [2001=100]
    idx_base = detect_index_base_metadata(full_line)
    if idx_base:
        try:
            val_int = int(float(num_clean))
            if val_int == idx_base["index_base_year"]:
                return ROLE_INDEX_BASE_YEAR, 0.99
            if val_int == idx_base["index_base_value"]:
                return ROLE_INDEX_BASE_VALUE, 0.99
        except ValueError:
            pass

    # 4. Table Column Sequence / Header Index Check:
    # e.g. "1 2 3 4 5 6 7 8 9 10" in table header rows
    if re.match(r'^\d{1,2}$', num_clean) and re.match(r'^(?:\d{1,2}\s+){3,}\d{1,2}$', line_clean):
        return ROLE_COLUMN_IDENTIFIER, 0.98

    # 5. Page Reference Check:
    if detect_navigation_reference(full_line):
        return ROLE_PAGE_REFERENCE, 0.95
    if re.search(r'\b(?:page|p\.?)\s*' + re.escape(num_clean) + r'\b', combined):
        return ROLE_PAGE_REFERENCE, 0.95

    # 6. Note Reference Check:
    if re.search(r'\b(?:note|footnote)\s*' + re.escape(num_clean) + r'\b', combined):
        return ROLE_NOTE_REFERENCE, 0.95

    # 7. Year Check:
    if re.match(r'^(?:19|20)\d{2}$', num_clean):
        if re.search(r'\b(?:fy|fiscal|quarter|q[1-4]|year|ended|as at|march|december|june|september)\b', combined):
            return ROLE_YEAR, 0.95
        if not re.search(r'(?:₹|\$|inr|usd|rs|percent|\%|shares|parcels|employees)', val_unit):
            return ROLE_YEAR, 0.90
    elif re.match(r'^\d{2}$', num_clean) and re.search(r'\b(?:fy|fiscal|q[1-4]\s*fy|20)\s*' + re.escape(num_clean) + r'\b', combined):
        return ROLE_YEAR, 0.95

    # 8. Date Component Check:
    if re.search(r'\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+' + re.escape(num_clean) + r'\b', combined):
        return ROLE_DATE_COMPONENT, 0.95
    if re.search(r'\b' + re.escape(num_clean) + r'\s+(?:months?|days?)\s+ended\b', combined):
        return ROLE_DATE_COMPONENT, 0.95

    # 9. Share Count Check:
    if re.search(r'\b(?:shares?|equity shares?|preference shares?|securities)\b', val_unit):
        return ROLE_SHARE_COUNT, 0.95
    if re.search(r'\b' + re.escape(num_clean) + r'\s+(?:equity|preference)?\s*shares?\b', combined):
        return ROLE_SHARE_COUNT, 0.90

    # 10. Money Check:
    if any(sym in val_unit for sym in ["₹", "$", "inr", "usd", "rs", "rs.", "rupees", "dollars"]):
        return ROLE_MONEY, 0.95
    if re.search(r'(?:₹|\$|inr|usd|rs\.?)\s*(?:\w+\s+){0,2}' + re.escape(num_clean), combined):
        return ROLE_MONEY, 0.90

    # 11. Percentage Check:
    if "%" in val_unit or "percent" in val_unit or "percentage" in val_unit:
        return ROLE_PERCENT, 0.95
    if re.search(r'\b' + re.escape(num_clean) + r'\s*(?:\%|percent|percentage)\b', combined):
        return ROLE_PERCENT, 0.90

    # 12. Quantity / Count Check:
    if re.search(r'\b(?:parcels?|orders?|shipments?|employees?|headcount|workers?|facilities|hubs|vehicles|centres|tonnes|metric tonnes)\b', combined):
        return ROLE_COUNT, 0.90

    return ROLE_METRIC_VALUE, 0.70

def is_metric_value_role(role: str) -> bool:
    """Returns True ONLY for roles that legitimately populate a metric value."""
    return role in METRIC_VALUE_ROLES

def canonicalize_metric(metric_name: str) -> str:
    """
    Generic metric canonicalization preserving critical semantic modifiers:
    adjusted, margin, growth, net, gross, total, operating, segment, consolidated, standalone, yoy, qoq, female, male.
    """
    if not metric_name:
        return "unspecified_metric"
        
    raw = metric_name.lower().strip()
    
    # 1. Alias map for known domain synonyms - preserve specific metric types
    aliases = {
        "express parcel orders": "express_parcel_shipment_volume",
        "express parcel orders fulfilled": "express_parcel_shipment_volume",
        "express parcel shipment volume": "express_parcel_shipment_volume",
        "express parcel volumes": "express_parcel_shipment_volume",
        "express parcel shipment volumes": "express_parcel_shipment_volume",
        # Specific Inflation Metrics
        "cpi": "headline_cpi_inflation",
        "cpi inflation": "headline_cpi_inflation",
        "headline cpi inflation": "headline_cpi_inflation",
        "retail headline inflation": "headline_cpi_inflation",
        "headline inflation": "headline_cpi_inflation",
        "consumer price index": "headline_cpi_inflation",
        "consumer price index cpi": "headline_cpi_inflation",
        "general index all groups": "headline_cpi_inflation",
        "all india cpi combined general index": "headline_cpi_inflation",
        "cpi industrial workers": "cpi_industrial_workers_inflation",
        "cpi-industrial workers": "cpi_industrial_workers_inflation",
        "cpi-iw": "cpi_industrial_workers_inflation",
        "cpi industrial workers iw": "cpi_industrial_workers_inflation",
        "cpi iw inflation": "cpi_industrial_workers_inflation",
        "core inflation": "core_inflation",
        "core cpi inflation": "core_inflation",
        "food inflation": "food_inflation",
        "food and beverages inflation": "food_inflation",
        "wpi inflation": "wpi_inflation",
        "wholesale price index": "wpi_inflation",
        # GDP Metrics
        "gdp growth": "real_gdp_growth",
        "gdp growth rate": "real_gdp_growth",
        "real gdp growth": "real_gdp_growth",
        "real gross domestic product gdp growth": "real_gdp_growth",
        "real gross domestic product growth": "real_gdp_growth",
        # Monetary Policy Metrics
        "repo rate": "policy_repo_rate",
        "policy repo rate": "policy_repo_rate",
        "policy repo rate change": "policy_repo_rate_change",
        "repo rate change": "policy_repo_rate_change",
        "spread to policy repo rate": "spread_to_policy_repo_rate",
        # Workforce
        "female workforce growth": "female_workforce_yoy_growth",
        "female workforce yoy growth": "female_workforce_yoy_growth",
        "female workers yoy growth": "female_workforce_yoy_growth",
        "female workers": "female_workforce_yoy_growth",
    }
    
    if raw in aliases:
        return aliases[raw]
        
    # 2. Generic token canonicalization
    raw = re.sub(r'\bpat\b', 'profit_after_tax', raw)
    raw = re.sub(r'\bebita\b', 'ebitda', raw)

    clean = re.sub(r'[^a-z0-9\s_]', ' ', raw)
    tokens = clean.split()
    
    stopwords = {"the", "and", "of", "in", "for", "to", "a", "from", "on", "was", "reported", "as", "reached", "level", "figure", "data", "states", "shows", "claim", "company", "limited", "value", "our", "number", "rate"}
    
    canonical_tokens = []
    for token in tokens:
        if token in stopwords:
            continue
        if token.endswith('s') and len(token) > 3 and not token.endswith(('ss', 'us', 'is', 'gross')):
            token = token[:-1]
        canonical_tokens.append(token)
        
    if not canonical_tokens:
        return "unspecified_metric"
        
    return "_".join(canonical_tokens)
