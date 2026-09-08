import unittest
from app.number_classifier import (
    classify_number_role, detect_index_base_metadata, is_metric_value_role,
    ROLE_FOOTNOTE_REFERENCE, ROLE_ROW_IDENTIFIER, ROLE_INDEX_BASE_VALUE,
)
from app.extraction import extract_facts_from_chunk_mock
from app.matching import find_candidate_pairs, judge_relationship_mock

class TestSemanticRegressions(unittest.TestCase):

    def test_footnote_74_is_not_cash_flow(self):
        role, _ = classify_number_role("74", raw_val="74", full_line="74 Offering collateral-free financing improves cash flow")
        self.assertEqual(role, ROLE_FOOTNOTE_REFERENCE)
        self.assertFalse(is_metric_value_role(role))

    def test_ii_2_is_not_inflation_value(self):
        role, _ = classify_number_role("2", raw_val="2", full_line="2. CPI-Industrial Workers (IW) [2001=100]")
        self.assertEqual(role, ROLE_ROW_IDENTIFIER)
        self.assertFalse(is_metric_value_role(role))

    def test_2001_100_is_index_base_metadata(self):
        self.assertEqual(detect_index_base_metadata("CPI-IW [2001=100]"), {"index_base_year": 2001, "index_base_value": 100})
        role, _ = classify_number_role("100", raw_val="100", full_line="CPI-IW [2001=100]")
        self.assertEqual(role, ROLE_INDEX_BASE_VALUE)
        self.assertFalse(is_metric_value_role(role))

    def test_table_column_numbers_not_facts(self):
        facts, _ = extract_facts_from_chunk_mock("1 2 3 4 5 6 7 8 9 10", 1, "RBI.pdf")
        self.assertFalse(facts)

    def test_delhivery_annual_report_289_extracted_as_fy2021(self):
        facts, _ = extract_facts_from_chunk_mock("Express parcel shipment volume (million)\nFY20 FY21 FY22 FY23 FY24\n225 289 582 663 740", 1, "Delhivery FY24.pdf")
        fact = next(f for f in facts if f["period"] == "FY 2021")
        self.assertEqual(fact["normalized_value"], 289)
        self.assertEqual(fact["normalized_unit"], "million_parcels")
        self.assertEqual(fact["binding_method"], "table_series_alignment")

    def test_289_20_vs_289_corroborates(self):
        a = {"id": 1, "document_id": "d1", "entity": "Delhivery Limited", "metric": "express parcel orders fulfilled", "value": "289.20", "normalized_value": 289.2, "unit": "million parcels", "normalized_unit": "parcels", "value_type": "COUNT", "period": "FY2021"}
        b = {"id": 2, "document_id": "d2", "entity": "Delhivery Limited", "metric": "express parcel shipment volume", "value": "289", "normalized_value": 289, "unit": "million parcels", "normalized_unit": "parcels", "value_type": "COUNT", "period": "FY2021"}
        self.assertEqual(judge_relationship_mock(a, b)["relationship"], "CORROBORATES")

    def test_gdp_estimate_revision_reconciles(self):
        a = {"id": 1, "document_id": "d1", "subject_entity": "India", "entity": "Ministry of Finance", "metric": "real GDP growth", "value": "6.4%", "normalized_value": 6.4, "unit": "%", "normalized_unit": "%", "value_type": "PERCENT", "period": "FY2024-25", "estimate_vintage": "FIRST_ADVANCE_ESTIMATE"}
        b = {"id": 2, "document_id": "d2", "subject_entity": "India", "entity": "Reserve Bank of India", "metric": "GDP growth", "value": "6.5%", "normalized_value": 6.5, "unit": "%", "normalized_unit": "%", "value_type": "PERCENT", "period": "FY2024-25", "estimate_vintage": "SECOND_ADVANCE_ESTIMATE"}
        result = judge_relationship_mock(a, b)
        self.assertEqual(result["relationship"], "RECONCILED")
        self.assertEqual(result["reconciliation_type"], "ESTIMATE_REVISION")

    def test_apr_dec_cpi_vs_full_year_is_scope_difference(self):
        a = {"id": 1, "document_id": "d1", "subject_entity": "India", "metric": "headline CPI inflation", "value": "4.9%", "normalized_value": 4.9, "unit": "%", "normalized_unit": "%", "value_type": "PERCENT", "period": "FY2024-25", "period_scope": "APR_DEC"}
        b = {"id": 2, "document_id": "d2", "subject_entity": "India", "metric": "CPI", "value": "4.6%", "normalized_value": 4.6, "unit": "%", "normalized_unit": "%", "value_type": "PERCENT", "period": "FY2024-25", "period_scope": "FULL_YEAR"}
        self.assertEqual(judge_relationship_mock(a, b)["relationship"], "TEMPORAL_COMPARISON")

    def test_source_org_not_subject_entity_and_exact_block_not_capped(self):
        base = {"metric": "headline CPI inflation", "value": "5.4%", "unit": "%", "normalized_value": 5.4, "normalized_unit": "%", "value_type": "PERCENT", "period": "FY2023-24"}
        facts = [dict(base, id=1, document_id="economic", subject_entity="India", entity="Ministry of Finance")]
        facts += [dict(base, id=i + 2, document_id=f"rbi-{i}", subject_entity="India", entity="Reserve Bank of India") for i in range(60)]
        pairs = find_candidate_pairs(facts, max_candidates=1)
        self.assertGreater(len(pairs), 1)

if __name__ == "__main__":
    unittest.main()
