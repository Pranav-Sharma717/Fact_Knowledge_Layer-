from app.number_classifier import (
    classify_number_role,
    ROLE_MONEY, ROLE_PERCENT, ROLE_SHARE_COUNT, ROLE_COUNT, ROLE_YEAR,
    ROLE_DATE_COMPONENT, ROLE_PAGE_REFERENCE, ROLE_NOTE_REFERENCE,
    is_metric_value_role, detect_navigation_reference
)
from app.validation import validate_fact_candidate, is_header_or_unit_label
from app.extraction import extract_facts_from_chunk_mock
from app.normalization import normalize_fact
from app.matching import judge_relationship_mock, can_compute_delta, calculate_comparability_score
from app.models import FactItem

def test_toc_page_number_is_not_fact():
    toc_line1 = "CAPITAL STRUCTURE .............................. 117"
    toc_line2 = "FINANCIAL INDEBTEDNESS ........ 513"
    
    assert detect_navigation_reference(toc_line1) is True
    assert detect_navigation_reference(toc_line2) is True
    
    cand1 = {
        "entity": "Delhivery Limited",
        "metric": "Capital Structure",
        "value": "117",
        "unit": None,
        "period": "FY2021",
        "raw_quote": toc_line1,
        "numeric_value": 117.0,
        "value_type": "INTEGER",
        "value_binding_confidence": 0.3
    }
    res = validate_fact_candidate(cand1)
    assert not res["valid"]
    assert res["failure_type"] == "NAVIGATION_REFERENCE" or "page reference" in res["rejection_reason"].lower()

def test_date_day_is_not_total_income():
    line = "and March 31, 2019 and total income"
    role_31, _ = classify_number_role("31", full_line=line)
    assert role_31 == ROLE_DATE_COMPONENT
    assert not is_metric_value_role(role_31)

def test_page_reference_is_not_ebitda_value():
    line_page = "refer to page 544 for details"
    role_544, _ = classify_number_role("544", full_line=line_page)
    assert role_544 == ROLE_PAGE_REFERENCE
    assert not is_metric_value_role(role_544)

    line_note = "see Note 14 to financial statements"
    role_14, _ = classify_number_role("14", full_line=line_note)
    assert role_14 == ROLE_NOTE_REFERENCE
    assert not is_metric_value_role(role_14)

def test_year_is_not_numeric_metric_value():
    line = "EBITDA margin in FY24"
    role_24, _ = classify_number_role("24", full_line=line)
    assert role_24 in (ROLE_YEAR, ROLE_DATE_COMPONENT)
    assert not is_metric_value_role(role_24)

def test_share_count_unit_is_shares_not_inr():
    norm = normalize_fact({"value": "107,517,088", "unit": "Equity Shares", "raw_quote": "107,517,088 Equity Shares", "metric": "Offer Equity Shares"})
    assert norm["normalized_value"] == 107517088.0
    assert norm["normalized_unit"] == "shares"
    assert norm["value_type"] == "SHARE_COUNT"

def test_money_unit_is_inr():
    norm = normalize_fact({"value": "52350", "unit": "₹ million", "raw_quote": "aggregating to ₹52,350 million", "metric": "Offer Size"})
    assert norm["normalized_value"] == 52350000000.0
    assert norm["normalized_unit"] == "INR"
    assert norm["value_type"] == "MONEY"

def test_multi_value_offer_sentence_extracts_share_count_and_money():
    sentence = "Offer of 107,517,088 Equity Shares aggregating to ₹52,350 million"
    facts, _ = extract_facts_from_chunk_mock(sentence, page_number=10, doc_filename="Prospectus.pdf")
    
    # Should extract both share count and monetary amount
    metrics = [f["metric"].lower() for f in facts]
    assert len(facts) >= 2
    assert any("share" in m for m in metrics)
    assert any("amount" in m or "size" in m for m in metrics)
    
    share_fact = next(f for f in facts if "share" in f["metric"].lower())
    assert share_fact["unit"] in ("shares", "Equity Shares")
    assert share_fact["normalized_unit"] == "shares"
    
    money_fact = next(f for f in facts if "amount" in f["metric"].lower() or "size" in f["metric"].lower())
    assert money_fact["normalized_unit"] == "INR"

def test_semantic_ebitda_profitability_has_no_numeric_24():
    sentence = "FY24 was our first full year of EBITDA profitability."
    facts, _ = extract_facts_from_chunk_mock(sentence, page_number=5, doc_filename="AR24.pdf")
    for f in facts:
        # None of the facts should have value = 24
        assert str(f["value"]) != "24"
        assert f["normalized_value"] != 24.0

def test_esop_count_not_matched_with_ebitda():
    fact_esop = {
        "id": 1, "document_id": "d1", "page": 1, "entity": "Delhivery Limited",
        "metric": "ESOP Pool Shares", "value": "1500000", "unit": "shares", "period": "FY2021",
        "raw_quote": "ESOP pool of 1,500,000 shares", "normalized_value": 1500000.0,
        "normalized_unit": "shares", "value_type": "COUNT", "is_numeric": True
    }
    fact_ebitda = {
        "id": 2, "document_id": "d2", "page": 1, "entity": "Delhivery Limited",
        "metric": "EBITDA", "value": "1266.41", "unit": "INR million", "period": "FY2024",
        "raw_quote": "EBITDA reached ₹1266.41 million", "normalized_value": 1266410000.0,
        "normalized_unit": "INR", "value_type": "MONEY", "is_numeric": True
    }
    
    score, passed, failed = calculate_comparability_score(fact_esop, fact_ebitda)
    assert score == 0.0
    assert not can_compute_delta(fact_esop, fact_ebitda)

def test_total_income_growth_percent_not_compared_as_total_income_value():
    fact_a = {"entity": "Delhivery", "metric": "Total income", "value_type": "MONEY", "normalized_unit": "INR"}
    fact_b = {"entity": "Delhivery", "metric": "Total income YoY growth", "value_type": "PERCENT", "normalized_unit": "%"}
    score, passed, failed = calculate_comparability_score(fact_a, fact_b)
    assert score == 0.0

def test_289_2_vs_289_corroborates():
    fact_a = {
        "id": 1, "document_id": "d1", "page": 47, "entity": "Delhivery Limited",
        "metric": "express parcel shipment volume", "value": "289.20", "unit": "million orders", "period": "FY2021",
        "raw_quote": "express parcel shipment volume reached 289.20 million orders",
        "normalized_value": 289200000.0, "normalized_unit": "orders", "value_type": "COUNT", "is_numeric": True
    }
    fact_b = {
        "id": 2, "document_id": "d2", "page": 6, "entity": "Delhivery Limited",
        "metric": "express parcel shipment volume", "value": "289", "unit": "million express parcel shipments", "period": "FY2021",
        "raw_quote": "handled 289 million express parcel shipments",
        "normalized_value": 289000000.0, "normalized_unit": "orders", "value_type": "COUNT", "is_numeric": True
    }
    
    res = judge_relationship_mock(fact_a, fact_b)
    assert res["relationship"] == "CORROBORATES"

def test_60_vs_59_likely_contradiction():
    fact_a = {
        "id": 1, "document_id": "d1", "page": 12, "entity": "Delhivery Limited",
        "metric": "female workforce YoY growth", "value": "60%", "unit": "percent", "period": "FY2024",
        "raw_quote": "female workers increased 60% year-on-year",
        "normalized_value": 60.0, "normalized_unit": "%", "value_type": "PERCENT", "is_numeric": True
    }
    fact_b = {
        "id": 2, "document_id": "d1", "page": 45, "entity": "Delhivery Limited",
        "metric": "female workforce YoY growth", "value": "59%", "unit": "percent", "period": "FY2024",
        "raw_quote": "number of female workers increased by 59% year-on-year",
        "normalized_value": 59.0, "normalized_unit": "%", "value_type": "PERCENT", "is_numeric": True
    }
    
    res = judge_relationship_mock(fact_a, fact_b)
    assert res["relationship"] in ("LIKELY_CONTRADICTION", "CONTRADICTS")

def test_unit_conversion_reconciliation():
    fact_a = {
        "id": 1, "document_id": "d1", "page": 10, "entity": "Delhivery Limited",
        "metric": "revenue from services", "value": "81415.38", "unit": "INR million", "period": "FY2024",
        "raw_quote": "Revenue from services was ₹81,415.38 million",
        "normalized_value": 81415380000.0, "normalized_unit": "INR", "value_type": "MONEY", "is_numeric": True
    }
    fact_b = {
        "id": 2, "document_id": "d2", "page": 4, "entity": "Delhivery Limited",
        "metric": "revenue from services", "value": "8142", "unit": "INR crore", "period": "FY2024",
        "raw_quote": "Revenue stood at ₹8,142 crore",
        "normalized_value": 81420000000.0, "normalized_unit": "INR", "value_type": "MONEY", "is_numeric": True
    }
    
    res = judge_relationship_mock(fact_a, fact_b)
    assert res["relationship"] in ("RECONCILED", "CORROBORATES")

def test_table_header_rejected():
    assert is_header_or_unit_label("(in ₹ million)") is True
    assert is_header_or_unit_label("Statement of Financial Position") is True

def test_valid_consumer_cases_amount_not_rejected():
    sentence = "Consumer cases filed against our Company before various forums amounting to ₹2.05 million."
    facts, _ = extract_facts_from_chunk_mock(sentence, page_number=15, doc_filename="Litigation.pdf")
    assert len(facts) >= 1
    f = facts[0]
    assert "2.05" in str(f["value"])
    assert f["normalized_value"] == 2050000.0
