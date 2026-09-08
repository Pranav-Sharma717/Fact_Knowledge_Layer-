import unittest
from app.number_classifier import (
    classify_number_role, canonicalize_metric,
    ROLE_PARAGRAPH_IDENTIFIER, ROLE_BASIS_POINT_CHANGE, ROLE_SPREAD,
    ROLE_METRIC_LEVEL, ROLE_PERCENT
)
from app.matching import (
    calculate_comparability_score, is_relationship_eligible_fact,
    judge_relationship_mock, TAXONOMY_CORROBORATES, TAXONOMY_TEMPORAL_COMPARISON
)
from app.models import RelationshipItem, FactItem
from app.main import rank_evaluator_candidates

class TestValueBindingQualityGate(unittest.TestCase):

    def test_section_1_12_not_inflation_value(self):
        """1.12 at start of paragraph/section heading must be classified as structural identifier, not metric value."""
        role, conf = classify_number_role(
            "1.12", raw_val="1.12", full_line="1.12 Inflation rates across economies have moderated in recent months."
        )
        self.assertEqual(role, ROLE_PARAGRAPH_IDENTIFIER)
        fact = {
            "entity": "India", "metric": "Inflation Rate", "value": "1.12",
            "normalized_value": 1.12, "unit": "%", "normalized_unit": "%",
            "raw_quote": "1.12 Inflation rates across economies have moderated in recent months."
        }
        self.assertFalse(is_relationship_eligible_fact(fact))

    def test_reduced_by_25_bps_is_rate_change_not_rate(self):
        """'reduced by 25 bps' is a RATE_CHANGE/DELTA, not policy repo rate level."""
        role, conf = classify_number_role(
            "25", raw_val="25", unit_str="bps",
            full_line="The MPC reduced the policy repo rate by 25 bps to 6.25 per cent."
        )
        self.assertEqual(role, ROLE_BASIS_POINT_CHANGE)
        # If incorrectly labeled as Repo Rate level, quality gate must reject it
        bad_fact = {
            "entity": "India", "metric": "Policy Repo Rate", "value": "25",
            "normalized_value": 25.0, "unit": "bps", "normalized_unit": "bps",
            "raw_quote": "The MPC reduced the policy repo rate by 25 bps to 6.25 per cent."
        }
        self.assertFalse(is_relationship_eligible_fact(bad_fact))

    def test_6_bps_above_repo_is_spread_not_repo_rate(self):
        """'6 bps above the policy repo rate' is SPREAD, not repo rate level."""
        role, conf = classify_number_role(
            "6", raw_val="6", unit_str="bps",
            full_line="The weighted average call rate traded 6 bps above the policy repo rate."
        )
        self.assertEqual(role, ROLE_SPREAD)
        bad_fact = {
            "entity": "India", "metric": "Repo Rate", "value": "6",
            "normalized_value": 6.0, "unit": "bps", "normalized_unit": "bps",
            "raw_quote": "The weighted average call rate traded 6 bps above the policy repo rate."
        }
        self.assertFalse(is_relationship_eligible_fact(bad_fact))

    def test_generic_inflation_not_used_as_canonical_metric(self):
        """Canonical metric preserves specific inflation sub-types and never collapses to generic 'inflation'."""
        self.assertEqual(canonicalize_metric("Retail headline inflation"), "headline_cpi_inflation")
        self.assertEqual(canonicalize_metric("Headline inflation"), "headline_cpi_inflation")
        self.assertEqual(canonicalize_metric("Core inflation"), "core_inflation")
        self.assertEqual(canonicalize_metric("Food inflation"), "food_inflation")
        self.assertEqual(canonicalize_metric("CPI-Industrial Workers"), "cpi_industrial_workers_inflation")
        self.assertEqual(canonicalize_metric("WPI inflation"), "wpi_inflation")
        
        # None of these should equal 'inflation'
        for m in ["Retail headline inflation", "Core inflation", "Food inflation", "CPI-IW"]:
            self.assertNotEqual(canonicalize_metric(m), "inflation")

    def test_unresolved_unit_blocks_strong_relationship(self):
        """Missing or unresolved unit blocks strong numeric comparison."""
        fact_a = {
            "id": 1, "document_id": "doc1", "subject_entity": "India", "metric": "headline_cpi_inflation",
            "value": "5.4", "normalized_value": 5.4, "unit": "%", "normalized_unit": "%", "value_type": "PERCENT", "period": "FY 2023-24"
        }
        fact_b_no_unit = {
            "id": 2, "document_id": "doc2", "subject_entity": "India", "metric": "headline_cpi_inflation",
            "value": "5.4", "normalized_value": 5.4, "unit": None, "normalized_unit": None, "value_type": "PERCENT", "period": "FY 2023-24"
        }
        score, passed, failed = calculate_comparability_score(fact_a, fact_b_no_unit)
        self.assertEqual(score, 0.0)
        self.assertTrue(any("unit" in f.lower() or "quality gate" in f.lower() for f in failed))

    def test_temporal_comparison_requires_specific_metric(self):
        """Temporal comparisons require specific canonical metric match, not generic category overlap."""
        cpi_fact = {
            "id": 1, "document_id": "doc1", "subject_entity": "India", "metric": "Retail Headline Inflation",
            "value": "5.4%", "normalized_value": 5.4, "unit": "%", "normalized_unit": "%", "value_type": "PERCENT", "period": "FY 2023-24"
        }
        core_fact = {
            "id": 2, "document_id": "doc2", "subject_entity": "India", "metric": "Core Inflation",
            "value": "3.5%", "normalized_value": 3.5, "unit": "%", "normalized_unit": "%", "value_type": "PERCENT", "period": "FY 2024-25"
        }
        # Core Inflation vs Headline CPI must not be allowed to compare
        score, passed, failed = calculate_comparability_score(cpi_fact, core_fact)
        self.assertEqual(score, 0.0)
        self.assertTrue(any("mismatch" in f.lower() for f in failed))

    def test_evaluator_prefers_grounded_cpi_pair(self):
        """Evaluator candidate ranking prefers grounded 5.4% ↔ 5.4% CPI pair over arbitrary 1 ↔ 1 matches."""
        cpi_a = FactItem(
            id=1, document_id="doc1", chunk_id=1, entity="India", subject_entity="India", metric="Retail Headline Inflation",
            predicate="was reported as", value="5.4%", numeric_value=5.4, unit="%", normalized_value=5.4,
            normalized_unit="%", period="FY 2023-24", raw_quote="Headline inflation was 5.4% in FY24", page=28,
            extraction_confidence=0.95, grounding_confidence=1.0, value_binding_confidence=0.95, final_confidence=0.95,
            value_type="PERCENT", is_numeric=True, validation_status="valid"
        )
        cpi_b = FactItem(
            id=2, document_id="doc2", chunk_id=2, entity="India", subject_entity="India", metric="Headline Inflation",
            predicate="was reported as", value="5.4%", numeric_value=5.4, unit="%", normalized_value=5.4,
            normalized_unit="%", period="FY 2023-24", raw_quote="from 5.4 per cent in the previous year", page=9,
            extraction_confidence=0.95, grounding_confidence=1.0, value_binding_confidence=0.95, final_confidence=0.95,
            value_type="PERCENT", is_numeric=True, validation_status="valid"
        )
        trivial_a = FactItem(
            id=3, document_id="doc1", chunk_id=1, entity="Unknown Entity", subject_entity="Unknown Entity", metric="Count Item",
            predicate="states", value="1", numeric_value=1.0, unit="", normalized_value=1.0,
            normalized_unit="", period="2024", raw_quote="Item 1", page=1,
            extraction_confidence=0.5, grounding_confidence=0.5, value_binding_confidence=0.5, final_confidence=0.5,
            value_type="COUNT", is_numeric=True, validation_status="valid"
        )
        trivial_b = FactItem(
            id=4, document_id="doc2", chunk_id=2, entity="Unknown Entity", subject_entity="Unknown Entity", metric="Count Item",
            predicate="states", value="1", numeric_value=1.0, unit="", normalized_value=1.0,
            normalized_unit="", period="2024", raw_quote="Item 1", page=1,
            extraction_confidence=0.5, grounding_confidence=0.5, value_binding_confidence=0.5, final_confidence=0.5,
            value_type="COUNT", is_numeric=True, validation_status="valid"
        )
        
        rel_cpi = RelationshipItem(
            id=10, fact_id_a=1, fact_id_b=2, relationship_type=TAXONOMY_CORROBORATES,
            taxonomy_category=TAXONOMY_CORROBORATES, reasoning="Corroboration", confidence=0.95,
            comparison_delta=0.0, can_compute_delta=True, reconciliation_type="NONE",
            match_checklist=[], pipeline_version=4, fact_a=cpi_a, fact_b=cpi_b
        )
        rel_trivial = RelationshipItem(
            id=20, fact_id_a=3, fact_id_b=4, relationship_type=TAXONOMY_CORROBORATES,
            taxonomy_category=TAXONOMY_CORROBORATES, reasoning="Trivial", confidence=0.75,
            comparison_delta=0.0, can_compute_delta=True, reconciliation_type="NONE",
            match_checklist=[], pipeline_version=4, fact_a=trivial_a, fact_b=trivial_b
        )
        
        ranked = rank_evaluator_candidates([rel_trivial, rel_cpi], TAXONOMY_CORROBORATES)
        self.assertEqual(ranked[0].id, 10)

    def test_gdp_fae_sae_reconciliation_selected(self):
        """GDP 6.4% FAE vs 6.5% SAE is reconciled as ESTIMATE_REVISION."""
        gdp_fae = {
            "id": 1, "document_id": "survey", "subject_entity": "India", "metric": "Real GDP Growth",
            "value": "6.4 per cent", "normalized_value": 6.4, "unit": "%", "normalized_unit": "%",
            "value_type": "PERCENT", "period": "FY 2024-25", "estimate_vintage": "FIRST_ADVANCE_ESTIMATE"
        }
        gdp_sae = {
            "id": 2, "document_id": "rbi", "subject_entity": "India", "metric": "Real GDP Growth",
            "value": "6.5 per cent", "normalized_value": 6.5, "unit": "%", "normalized_unit": "%",
            "value_type": "PERCENT", "period": "FY 2024-25", "estimate_vintage": "SECOND_ADVANCE_ESTIMATE"
        }
        res = judge_relationship_mock(gdp_fae, gdp_sae)
        self.assertEqual(res["relationship"], "RECONCILED")
        self.assertEqual(res["reconciliation_type"], "ESTIMATE_REVISION")

    def test_invalid_fact_cannot_enter_relationship_engine(self):
        """Invalid/suspicious facts (section numbers, axis ticks, spread as level) cannot enter the matching engine."""
        axis_fact = {
            "entity": "India", "metric": "Inflation Rate", "value": "-24",
            "normalized_value": -24.0, "unit": "%", "normalized_unit": "%",
            "raw_quote": "Chart I.45: -24"
        }
        self.assertFalse(is_relationship_eligible_fact(axis_fact))
        
        sec_fact = {
            "entity": "India", "metric": "Inflation Rate", "value": "1.52",
            "normalized_value": 1.52, "unit": "%", "normalized_unit": "%",
            "raw_quote": "1.52 Retail headline inflation has softened"
        }
        self.assertFalse(is_relationship_eligible_fact(sec_fact))

    def test_attached_footnote_number_classified_as_footnote(self):
        """Numbers attached to acronyms or words like (GDP)3 must be classified as footnote reference, not metric."""
        role, conf = classify_number_role(
            "3", raw_val="3",
            full_line="Although real gross domestic product (GDP)3 growth moderated to 6.5 per cent in 2024-25"
        )
        self.assertEqual(role, "FOOTNOTE_REFERENCE")

    def test_section_outline_code_classified_as_structural(self):
        """Outline codes like 3B.1.1 must be classified as structural identifiers."""
        role, conf = classify_number_role(
            "3", raw_val="3",
            full_line="3B.1.1 Market Borrowings (net)"
        )
        self.assertEqual(role, ROLE_PARAGRAPH_IDENTIFIER)

    def test_cpi_scope_difference_evaluation(self):
        """Headline CPI 4.9% APR_DEC vs 4.6% FULL_YEAR for FY25 evaluates to TEMPORAL_COMPARISON with SCOPE_PERIOD_DIFFERENCE."""
        cpi_partial = {
            "id": 1, "document_id": "survey", "subject_entity": "India", "metric": "Retail Headline Inflation",
            "value": "4.9 per cent", "normalized_value": 4.9, "unit": "%", "normalized_unit": "%",
            "value_type": "PERCENT", "period": "FY 2024-25", "period_scope": "APR_DEC"
        }
        cpi_full = {
            "id": 2, "document_id": "rbi", "subject_entity": "India", "metric": "Headline Inflation",
            "value": "4.6 per cent", "normalized_value": 4.6, "unit": "%", "normalized_unit": "%",
            "value_type": "PERCENT", "period": "FY 2024-25", "period_scope": "FULL_YEAR"
        }
        res = judge_relationship_mock(cpi_partial, cpi_full)
        self.assertEqual(res["relationship"], TAXONOMY_TEMPORAL_COMPARISON)
        self.assertEqual(res["reconciliation_type"], "SCOPE_PERIOD_DIFFERENCE")

if __name__ == "__main__":
    unittest.main()
