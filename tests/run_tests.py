import unittest
from tests.test_fact_knowledge_layer import (
    test_normalization_currencies_and_magnitudes,
    test_table_header_and_bare_unit_validation,
    test_comparability_filtering_unrelated_metrics,
    test_reconciled_unit_conversion,
    test_reconciled_period_difference,
    test_corroboration
)
from tests.test_golden_dataset import (
    test_toc_page_number_is_not_fact,
    test_date_day_is_not_total_income,
    test_page_reference_is_not_ebitda_value,
    test_year_is_not_numeric_metric_value,
    test_share_count_unit_is_shares_not_inr,
    test_money_unit_is_inr,
    test_multi_value_offer_sentence_extracts_share_count_and_money,
    test_semantic_ebitda_profitability_has_no_numeric_24,
    test_esop_count_not_matched_with_ebitda,
    test_total_income_growth_percent_not_compared_as_total_income_value,
    test_289_2_vs_289_corroborates,
    test_60_vs_59_likely_contradiction,
    test_unit_conversion_reconciliation,
    test_table_header_rejected,
    test_valid_consumer_cases_amount_not_rejected
)

class TestFactKnowledgeLayer(unittest.TestCase):
    def test_normalization(self):
        test_normalization_currencies_and_magnitudes()

    def test_validation(self):
        test_table_header_and_bare_unit_validation()

    def test_comparability(self):
        test_comparability_filtering_unrelated_metrics()

    def test_unit_conversion(self):
        test_reconciled_unit_conversion()

    def test_period_difference(self):
        test_reconciled_period_difference()

    def test_corroboration_case(self):
        test_corroboration()

    # Golden Dataset Tests
    def test_golden_toc_page_number(self):
        test_toc_page_number_is_not_fact()

    def test_golden_date_day(self):
        test_date_day_is_not_total_income()

    def test_golden_page_reference(self):
        test_page_reference_is_not_ebitda_value()

    def test_golden_year_numeric(self):
        test_year_is_not_numeric_metric_value()

    def test_golden_share_count_unit(self):
        test_share_count_unit_is_shares_not_inr()

    def test_golden_money_unit(self):
        test_money_unit_is_inr()

    def test_golden_multi_value(self):
        test_multi_value_offer_sentence_extracts_share_count_and_money()

    def test_golden_semantic_ebitda(self):
        test_semantic_ebitda_profitability_has_no_numeric_24()

    def test_golden_esop_vs_ebitda(self):
        test_esop_count_not_matched_with_ebitda()

    def test_golden_total_income_growth(self):
        test_total_income_growth_percent_not_compared_as_total_income_value()

    def test_golden_289_corroborates(self):
        test_289_2_vs_289_corroborates()

    def test_golden_60_vs_59_contradiction(self):
        test_60_vs_59_likely_contradiction()

    def test_golden_unit_reconciliation(self):
        test_unit_conversion_reconciliation()

    def test_golden_table_header(self):
        test_table_header_rejected()

    def test_golden_valid_consumer_cases(self):
        test_valid_consumer_cases_amount_not_rejected()

if __name__ == "__main__":
    unittest.main()
