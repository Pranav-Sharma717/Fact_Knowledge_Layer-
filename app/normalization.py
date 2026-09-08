import re
from typing import Dict, Any, Optional, Tuple
from app.number_classifier import classify_number_role, ROLE_MONEY, ROLE_PERCENT, ROLE_SHARE_COUNT, ROLE_COUNT, ROLE_QUANTITY, ROLE_UNKNOWN

MAGNITUDE_MULTIPLIERS = {
    "thousand": 1e3,
    "k": 1e3,
    "lakh": 1e5,
    "lacs": 1e5,
    "lac": 1e5,
    "million": 1e6,
    "mn": 1e6,
    "billion": 1e9,
    "bn": 1e9,
    "crore": 1e7,
    "cr": 1e7,
}

CURRENCY_MAP = {
    "₹": "INR",
    "inr": "INR",
    "rs": "INR",
    "rs.": "INR",
    "rupees": "INR",
    "$": "USD",
    "usd": "USD",
    "dollars": "USD"
}

def parse_raw_numeric(val_str: str) -> Optional[float]:
    """
    Extracts first float/int value from raw value string.
    Supports parenthesized negative financial numbers like (9.11%), (4,516.08), or ₹(100).
    """
    if not val_str:
        return None
    
    # 1. Check parenthesized negative financial format: (123.45) or ₹(123) or (9.11%)
    paren_match = re.search(r'\(\s*(?:₹|\$|inr|usd|rs\.?)?\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*\%?\s*\)', val_str, re.IGNORECASE)
    if paren_match:
        clean_num = paren_match.group(1).replace(',', '')
        try:
            return -abs(float(clean_num))
        except ValueError:
            pass

    # 2. Standard float matching with optional leading - or +
    match = re.search(r'[-+]?\d+(?:,\d+)*(?:\.\d+)?', val_str)
    if match:
        clean_num = match.group(0).replace(',', '')
        try:
            return float(clean_num)
        except ValueError:
            return None
    return None

def normalize_fact(fact: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizes numeric values and units generically according to number typing rules.
    Prevents false currency scaling on share counts or volume metrics and handles negative signs.
    """
    raw_val = str(fact.get("value", "")).strip()
    raw_unit = str(fact.get("unit", "") or "").strip()
    raw_quote = str(fact.get("raw_quote", "") or "").strip()
    metric = str(fact.get("metric", "")).strip()
    
    val_unit_text = f"{raw_val} {raw_unit}".lower()
    
    num_val = parse_raw_numeric(raw_val)
    if num_val is None:
        num_val = parse_raw_numeric(raw_unit)
        
    if num_val is None:
        return {
            "raw_value": raw_val,
            "numeric_value": None,
            "unit": raw_unit or None,
            "normalized_value": None,
            "normalized_unit": None,
            "value_type": "SEMANTIC",
            "explanation": "Non-numeric semantic claim.",
            "success": False
        }

    # Classify number role
    role, binding_conf = classify_number_role(
        num_str=f"{num_val:g}", raw_val=raw_val, unit_str=raw_unit, full_line=raw_quote
    )

    # 1. Percent Check (Task 4)
    if role == ROLE_PERCENT or "%" in val_unit_text or "percent" in val_unit_text:
        return {
            "raw_value": raw_val,
            "numeric_value": num_val,
            "unit": "%",
            "normalized_value": num_val,
            "normalized_unit": "%",
            "value_type": ROLE_PERCENT,
            "explanation": f"Normalized percentage: {num_val:g}%",
            "success": True
        }

    # 2. Share Count Normalization (Task 4)
    if (role == ROLE_SHARE_COUNT or "shares" in val_unit_text) and not any(curr in val_unit_text for curr in ["₹", "$", "inr", "usd", "rs"]):
        return {
            "raw_value": raw_val,
            "numeric_value": num_val,
            "unit": "shares",
            "normalized_value": num_val,
            "normalized_unit": "shares",
            "value_type": ROLE_SHARE_COUNT,
            "explanation": f"Normalized share count: {num_val:g} shares",
            "success": True
        }

    # 2. Money Currency Normalization
    detected_currency = None
    for k, v in CURRENCY_MAP.items():
        if k in val_unit_text:
            detected_currency = v
            break

    # 3. Check magnitude multiplier in value/unit text
    multiplier = 1.0
    detected_mag = None
    
    sorted_mags = sorted(MAGNITUDE_MULTIPLIERS.keys(), key=len, reverse=True)
    for mag_key in sorted_mags:
        pattern = r'\b' + re.escape(mag_key) + r'\b'
        if re.search(pattern, val_unit_text):
            multiplier = MAGNITUDE_MULTIPLIERS[mag_key]
            detected_mag = mag_key
            break

    # Check near-proximity in raw_quote only if not found in value/unit
    if not detected_mag and raw_quote and num_val is not None:
        val_clean_escaped = re.escape(raw_val)
        for mag_key in sorted_mags:
            near_pattern = r'\b' + val_clean_escaped + r'[\s\w]{0,20}\b' + re.escape(mag_key) + r'\b'
            if re.search(near_pattern, raw_quote, re.IGNORECASE):
                multiplier = MAGNITUDE_MULTIPLIERS[mag_key]
                detected_mag = mag_key
                break

    norm_val = round(num_val * multiplier, 4)
    
    if not detected_currency and (detected_mag in {"crore", "cr", "lakh", "lacs", "lac"} or role == ROLE_MONEY or any(kw in f"{metric} {raw_quote}".lower() for kw in ["revenue", "profit", "ebitda", "income", "amount", "debt", "cost"])):
        detected_currency = "INR"
    
    # Determine normalized unit and value_type
    combined_val_unit = f"{val_unit_text} {detected_mag or ''}".lower()
    if "%" in combined_val_unit or "percent" in combined_val_unit or "percentage" in combined_val_unit or role == ROLE_PERCENT:
        norm_unit = "%"
        val_type = ROLE_PERCENT
    elif "parcel" in combined_val_unit or "order" in combined_val_unit or "shipment" in combined_val_unit:
        # Retain the stated operational scale instead of silently converting
        # it to an unlabelled base count.  This keeps 289.20 million parcels
        # directly comparable with 289 million parcels.
        if detected_mag:
            norm_val = num_val
            norm_unit = f"{detected_mag}_parcels"
        else:
            norm_unit = "parcels"
        val_type = ROLE_COUNT
    elif "employee" in combined_val_unit or "headcount" in combined_val_unit or "worker" in combined_val_unit:
        norm_unit = "employees"
        val_type = ROLE_COUNT
    elif detected_currency or role == ROLE_MONEY:
        norm_unit = detected_currency or "INR"
        val_type = ROLE_MONEY
    else:
        norm_unit = raw_unit or None
        val_type = role if role != ROLE_UNKNOWN else ROLE_QUANTITY

    explanation_parts = []
    if detected_mag:
        explanation_parts.append(f"scaled by '{detected_mag}' (x{multiplier:g})")
    if detected_currency:
        explanation_parts.append(f"currency identified as {detected_currency}")
        
    if norm_unit == "INR" and norm_val >= 1e7:
        crore_val = norm_val / 1e7
        expl_text = f"Normalized: {num_val:g} {raw_unit or ''} -> {norm_val:g} INR (equivalent to ₹{crore_val:,.3f} crore)"
    elif norm_val >= 1e6 and norm_unit in {"INR", "USD"}:
        mn_val = norm_val / 1e6
        expl_text = f"Normalized: {num_val:g} {raw_unit or ''} -> {norm_val:g} {norm_unit or ''} ({mn_val:g} million)"
    else:
        expl_text = f"Normalized: {num_val:g} {raw_unit or ''} -> {norm_val:g} {norm_unit or ''}"
        
    return {
        "raw_value": raw_val,
        "numeric_value": num_val,
        "unit": raw_unit or None,
        "normalized_value": norm_val,
        "normalized_unit": norm_unit,
        "value_type": val_type,
        "explanation": expl_text,
        "success": True
    }
