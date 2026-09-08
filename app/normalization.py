import re
from typing import Dict, Any, Optional, Tuple

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
    """Extracts first float/int value from raw value string."""
    if not val_str:
        return None
    # Find match like 81,415.38 or 289.20 or 740 or -15.5
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
    Normalizes numeric values and units generically for currency, volumes, percentages.
    Returns dict with:
      - raw_value
      - numeric_value
      - unit
      - normalized_value
      - normalized_unit
      - explanation
      - success
    """
    raw_val = str(fact.get("value", "")).strip()
    raw_unit = str(fact.get("unit", "") or "").strip()
    raw_quote = str(fact.get("raw_quote", "") or "").strip()
    
    combined_text = f"{raw_val} {raw_unit} {raw_quote}".lower()
    
    num_val = parse_raw_numeric(raw_val)
    if num_val is None:
        num_val = parse_raw_numeric(raw_unit) or parse_raw_numeric(raw_quote)
        
    if num_val is None:
        return {
            "raw_value": raw_val,
            "numeric_value": None,
            "unit": raw_unit or None,
            "normalized_value": None,
            "normalized_unit": None,
            "explanation": "Non-numeric semantic claim.",
            "success": False
        }
        
    # Check currency
    detected_currency = None
    for k, v in CURRENCY_MAP.items():
        if k in combined_text:
            detected_currency = v
            break
            
    # Check magnitude multiplier
    multiplier = 1.0
    detected_mag = None
    
    # Sort magnitude keys by length descending to match 'million' before 'm'
    sorted_mags = sorted(MAGNITUDE_MULTIPLIERS.keys(), key=len, reverse=True)
    for mag_key in sorted_mags:
        # Match whole word or symbol
        pattern = r'\b' + re.escape(mag_key) + r'\b'
        if re.search(pattern, combined_text):
            multiplier = MAGNITUDE_MULTIPLIERS[mag_key]
            detected_mag = mag_key
            break
            
    norm_val = num_val * multiplier
    
    if not detected_currency and detected_mag in {"crore", "cr", "lakh", "lacs", "lac"}:
        detected_currency = "INR"
    
    # Determine normalized unit
    if "%" in combined_text or "percent" in combined_text or "percentage" in combined_text:
        norm_unit = "%"
    elif "parcel" in combined_text or "order" in combined_text or "shipment" in combined_text:
        norm_unit = "parcels"
    elif "employee" in combined_text or "headcount" in combined_text or "worker" in combined_text or "staff" in combined_text:
        norm_unit = "employees"
    elif detected_currency:
        norm_unit = detected_currency
    else:
        norm_unit = raw_unit or None
        
    explanation_parts = []
    if detected_mag:
        explanation_parts.append(f"scaled by '{detected_mag}' (x{multiplier:g})")
    if detected_currency:
        explanation_parts.append(f"currency identified as {detected_currency}")
        
    if norm_unit == "INR" and norm_val >= 1e7:
        crore_val = norm_val / 1e7
        expl_text = f"Normalized: {num_val:g} {raw_unit or ''} -> {norm_val:g} INR (equivalent to ₹{crore_val:,.3f} crore)"
    elif norm_val >= 1e6:
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
        "explanation": expl_text,
        "success": True
    }
