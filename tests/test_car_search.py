from __future__ import annotations

import unittest

from app.services.car_search import CarSearchService
from app.supabase_repo import SupabaseRepo


class CarSearchGClassNormalizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = CarSearchService(SupabaseRepo())

    def test_gelik_query_extracts_mercedes_g_class(self) -> None:
        criteria = self.service._build_criteria("что есть по геликам?", {})

        self.assertEqual(criteria["brand"], "Mercedes-Benz")
        self.assertEqual(criteria["model"], "G-Класс")

    def test_g63_query_extracts_amg_model(self) -> None:
        criteria = self.service._build_criteria("г63", {})

        self.assertEqual(criteria["brand"], "Mercedes-Benz")
        self.assertEqual(criteria["model"], "G-Класс AMG")
        self.assertIn("63", criteria["must_have"])
        self.assertIn("AMG", criteria["must_have"])

    def test_latin_g_class_matches_cyrillic_g_class_amg(self) -> None:
        row = {
            "brand": "Mercedes-Benz",
            "model": "G-Класс AMG",
            "pseudoModel": "G-Класс AMG 63 AMG",
            "year": 2026,
            "saleStatus": "onsale",
            "dealerSitePublicationUrl": "https://millionmiles.ru/car/test-g63/",
        }
        car = self.service._canonicalize(row)
        self.assertIsNotNone(car)

        criteria = self.service._build_criteria(
            "приятно познакомиться, а что есть у вас по геликам?",
            {"brand": "Mercedes-Benz", "model": "G-Class"},
        )

        self.assertTrue(self.service._matches_core_identity(car, criteria))
        self.assertGreater(self.service._score(car, criteria, "что есть по геликам"), 0.15)


if __name__ == "__main__":
    unittest.main()
