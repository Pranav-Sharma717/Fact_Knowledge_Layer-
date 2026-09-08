import unittest
from tests.test_fact_knowledge_layer import (
    test_normalization_currencies_and_magnitudes,
    test_table_header_and_bare_unit_validation,
    test_comparability_filtering_unrelated_metrics,
    test_reconciled_unit_conversion,
    test_reconciled_period_difference,
    test_corroboration
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

if __name__ == "__main__":
    unittest.main()
