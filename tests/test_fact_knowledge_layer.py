import os
import sqlite3
from app.normalization import normalize_fact, parse_raw_numeric
from app.validation import validate_fact_candidate, is_header_or_unit_label
from app.matching import calculate_comparability_score, judge_relationship_mock, find_candidate_pairs

def test_normalization_currencies_and_magnitudes():
    # INR Million
    f1 = {"value": "₹81,415.38 million", "unit": "INR", "raw_quote": "Revenue was ₹81,415.38 million"}
    n1 = normalize_fact(f1)
    assert n1["numeric_value"] == 81415.38
    assert n1["normalized_value"] == 81415.38 * 1e6
    assert n1["normalized_unit"] == "INR"

    # INR Crore
    f2 = {"value": "8,141.538 crore", "unit": "crore", "raw_quote": "Revenue was 8,141.538 crore"}
    n2 = normalize_fact(f2)
    assert n2["numeric_value"] == 8141.538
    assert n2["normalized_value"] == 8141.538 * 1e7
    assert n2["normalized_unit"] == "INR"
    assert n1["normalized_value"] == n2["normalized_value"]

    # Percentage
    f3 = {"value": "15.5%", "unit": "%", "raw_quote": "EBITDA margin was 15.5%"}
    n3 = normalize_fact(f3)
    assert n3["numeric_value"] == 15.5
    assert n3["normalized_value"] == 15.5
    assert n3["normalized_unit"] == "%"

def test_table_header_and_bare_unit_validation():
    # Table unit header
    cand1 = {
        "entity": "Unknown Entity",
        "metric": "Table Header",
        "predicate": "states",
        "value": "(₹ in million)",
        "raw_quote": "(₹ in million)",
        "extraction_confidence": 0.9
    }
    v1 = validate_fact_candidate(cand1)
    assert v1["valid"] is False
    assert v1["failure_type"] == "TABLE_HEADER_WITHOUT_VALUE"

    # Bare unit
    cand2 = {
        "entity": "Unknown Entity",
        "metric": "Unit",
        "predicate": "states",
        "value": "million",
        "raw_quote": "million",
        "extraction_confidence": 0.9
    }
    v2 = validate_fact_candidate(cand2)
    assert v2["valid"] is False
    assert v2["failure_type"] == "TABLE_HEADER_WITHOUT_VALUE"

    # Generic subject and predicate without metric
    cand3 = {
        "entity": "Document Claim",
        "metric": "",
        "predicate": "states",
        "value": "100",
        "raw_quote": "Document Claim states 100",
        "extraction_confidence": 0.9
    }
    v3 = validate_fact_candidate(cand3)
    assert v3["valid"] is False
    assert v3["failure_type"] == "VALUE_WITHOUT_METRIC"

def test_comparability_filtering_unrelated_metrics():
    # 0.00% EBITDA margin vs 0.00% Attrition rate
    fact_a = {
        "id": 1, "document_id": "doc1", "entity": "Delhivery", "metric": "EBITDA Margin",
        "predicate": "was", "value": "0.00%", "normalized_value": 0.0, "normalized_unit": "%"
    }
    fact_b = {
        "id": 2, "document_id": "doc2", "entity": "Delhivery", "metric": "Employee Attrition Rate",
        "predicate": "was", "value": "0.00%", "normalized_value": 0.0, "normalized_unit": "%"
    }
    
    score, _, _ = calculate_comparability_score(fact_a, fact_b)
    assert score == 0.0
    
    j_res = judge_relationship_mock(fact_a, fact_b)
    assert j_res["relationship"] == "UNRELATED"

def test_reconciled_unit_conversion():
    fact_a = {
        "id": 1, "document_id": "doc1", "entity": "Delhivery", "metric": "Revenue from Operations",
        "predicate": "was", "value": "₹81,415.38 million", "unit": "million",
        "normalized_value": 81415380000.0, "normalized_unit": "INR", "period": "FY 2023"
    }
    fact_b = {
        "id": 2, "document_id": "doc2", "entity": "Delhivery", "metric": "Revenue from Operations",
        "predicate": "was", "value": "8,141.538 crore", "unit": "crore",
        "normalized_value": 81415380000.0, "normalized_unit": "INR", "period": "FY 2023"
    }
    
    j_res = judge_relationship_mock(fact_a, fact_b)
    assert j_res["relationship"] == "RECONCILED"
    assert j_res["reconciliation_type"] == "UNIT_CONVERSION"

def test_reconciled_period_difference():
    fact_a = {
        "id": 1, "document_id": "doc1", "entity": "Delhivery", "metric": "Revenue from Operations",
        "predicate": "was", "value": "₹81,415.38 million", "unit": "million",
        "normalized_value": 81415380000.0, "normalized_unit": "INR", "period": "FY 2023"
    }
    fact_b = {
        "id": 2, "document_id": "doc2", "entity": "Delhivery", "metric": "Revenue from Operations",
        "predicate": "was", "value": "₹90,000.00 million", "unit": "million",
        "normalized_value": 90000000000.0, "normalized_unit": "INR", "period": "FY 2024"
    }
    
    j_res = judge_relationship_mock(fact_a, fact_b)
    assert j_res["relationship"] == "TEMPORAL_COMPARISON"
    assert j_res["reconciliation_type"] == "HISTORICAL_TREND"

def test_corroboration():
    fact_a = {
        "id": 1, "document_id": "doc1", "entity": "Delhivery", "metric": "Express Parcel Volume",
        "predicate": "was", "value": "289.20 million", "unit": "million",
        "normalized_value": 289200000.0, "normalized_unit": "PARCELS", "period": "FY 2023"
    }
    fact_b = {
        "id": 2, "document_id": "doc2", "entity": "Delhivery", "metric": "Express Parcel Volume",
        "predicate": "was", "value": "289.2 million", "unit": "million",
        "normalized_value": 289200000.0, "normalized_unit": "PARCELS", "period": "FY 2023"
    }
    
    j_res = judge_relationship_mock(fact_a, fact_b)
    assert j_res["relationship"] == "CORROBORATES"
