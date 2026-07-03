from __future__ import annotations

import unittest

from app.services.car_search import CarSearchService


class FakeSupabaseRepo:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    async def search_cars_raw(self, filters: dict) -> list[dict]:
        return self.rows


TEST_ROWS = [
    {
        "brand": "Mercedes-Benz",
        "model": "G-Класс AMG",
        "pseudoModel": "G-Класс AMG 63 AMG",
        "modificationName": "63 AMG 4.0 AT (585 л.с.) 4WD",
        "equipmentName": "AMG G 63",
        "year": 2026,
        "saleStatus": "onsale",
        "stockState": "in",
        "sellingPrice": 32500000,
        "dealerSitePublicationUrl": "https://millionmiles.ru/cars/mercedes-benz/g-klass-amg/test",
        "publicationDescription": "Пакет AMG Performance. Карбоновые элементы. Тормозная система AMG.",
    },
    {
        "brand": "Porsche",
        "model": "911",
        "pseudoModel": "911 Turbo S",
        "modificationName": "Turbo S 3.8 AMT (650 л.с.) 4WD",
        "equipmentName": "Turbo S",
        "year": 2024,
        "saleStatus": "onsale",
        "stockState": "in",
        "sellingPrice": 31990000,
        "dealerSitePublicationUrl": "https://millionmiles.ru/cars/porsche/911/test",
        "publicationDescription": "Карбон-керамические тормоза PCCB. Спорт пакет.",
    },
    {
        "brand": "Porsche",
        "model": "Cayenne",
        "pseudoModel": "Cayenne GTS Coupé",
        "modificationName": "GTS Coupé 4.0 AT (500 л.с.) 4WD",
        "equipmentName": "GTS Coupe",
        "year": 2024,
        "saleStatus": "onsale",
        "stockState": "in",
        "sellingPrice": 23990000,
        "dealerSitePublicationUrl": "https://millionmiles.ru/cars/porsche/cayenne/test",
        "publicationDescription": "GTS, керамические тормоза, Burmester, панорама.",
    },
    {
        "brand": "Porsche",
        "model": "Panamera",
        "pseudoModel": "Panamera 4",
        "modificationName": "4 2.9 AMT (353 л.с.) 4WD",
        "equipmentName": "Panamera 4",
        "year": 2025,
        "saleStatus": "onsale",
        "stockState": "in",
        "sellingPrice": 28990000,
        "dealerSitePublicationUrl": "https://millionmiles.ru/cars/porsche/panamera/test",
        "publicationDescription": "Комфортные сиденья, вентиляция.",
    },
    {
        "brand": "Bentley",
        "model": "Bentayga",
        "modificationName": "Speed 4.0 AT (650 л.с.) 4WD",
        "equipmentName": "Speed",
        "year": 2025,
        "saleStatus": "onsale",
        "stockState": "in",
        "sellingPrice": 42900000,
        "dealerSitePublicationUrl": "https://millionmiles.ru/cars/bentley/bentayga/test",
        "publicationDescription": "Bentayga Speed, массаж, вентиляция, Naim Audio.",
    },
    {
        "brand": "Bentley",
        "model": "Continental GT",
        "modificationName": "Speed 4.0hyb AMT (782 л.с.) 4WD",
        "equipmentName": "Speed",
        "year": 2025,
        "saleStatus": "onsale",
        "stockState": "in",
        "sellingPrice": 49865000,
        "dealerSitePublicationUrl": "https://millionmiles.ru/cars/bentley/continental-gt/test",
        "publicationDescription": "Continental GT Speed.",
    },
    {
        "brand": "BMW",
        "model": "X7",
        "pseudoModel": "X7 40d",
        "modificationName": "40d 3.0d AT (340 л.с.) 4WD",
        "equipmentName": "xDrive40d M Sport Pro",
        "year": 2025,
        "saleStatus": "onsale",
        "stockState": "in",
        "sellingPrice": 23840000,
        "dealerSitePublicationUrl": "https://millionmiles.ru/cars/bmw/x7/test",
        "publicationDescription": "BMW X7 с M Sport Pro, пневмоподвеска.",
    },
    {
        "brand": "Aston Martin",
        "model": "DBX",
        "modificationName": "DBX707 4.0 AT (707 л.с.) 4WD",
        "equipmentName": "DBX707",
        "year": 2025,
        "saleStatus": "onsale",
        "stockState": "in",
        "sellingPrice": 34500000,
        "dealerSitePublicationUrl": "https://millionmiles.ru/cars/aston-martin/dbx/test",
        "publicationDescription": "DBX707 SUV.",
    },
    {
        "brand": "Lamborghini",
        "model": "Urus",
        "pseudoModel": "Urus SE",
        "modificationName": "SE 4.0hyb AT (800 л.с.) 4WD",
        "equipmentName": "SE",
        "year": 2025,
        "saleStatus": "onsale",
        "stockState": "in",
        "sellingPrice": 34490000,
        "dealerSitePublicationUrl": "https://millionmiles.ru/cars/lamborghini/urus/test",
        "publicationDescription": "Urus SE, карбон-керамическая тормозная система.",
    },
]


class CarSearchGClassNormalizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = CarSearchService(FakeSupabaseRepo(TEST_ROWS))

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
        car = self.service._canonicalize(TEST_ROWS[0])
        self.assertIsNotNone(car)

        criteria = self.service._build_criteria(
            "приятно познакомиться, а что есть у вас по геликам?",
            {"brand": "Mercedes-Benz", "model": "G-Class"},
        )

        self.assertTrue(self.service._matches_core_identity(car, criteria))
        self.assertGreater(self.service._score(car, criteria, "что есть по геликам"), 0.15)


class CarSearchInventoryAwareTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = CarSearchService(FakeSupabaseRepo(TEST_ROWS))

    async def _top(self, query: str) -> dict:
        result = await self.service.search(query, {})
        self.assertTrue(result["found"], result)
        return result["cars"][0]

    async def test_x7_does_not_match_dbx707(self) -> None:
        car = await self._top("икс 7")

        self.assertEqual(car["brand"], "BMW")
        self.assertEqual(car["model"], "X7")

    async def test_bentayga_alias_returns_bentley_bentayga(self) -> None:
        car = await self._top("есть бентайга?")

        self.assertEqual(car["brand"], "Bentley")
        self.assertEqual(car["model"], "Bentayga")

    async def test_cayenne_gts_keeps_exact_model_and_trim(self) -> None:
        car = await self._top("каен gts")

        self.assertEqual(car["brand"], "Porsche")
        self.assertEqual(car["model"], "Cayenne")
        self.assertIn("GTS", car["modification"])

    async def test_porsche_911_turbo_returns_911_turbo(self) -> None:
        result = await self.service.search("порше 911 турбо", {})
        self.assertTrue(result["found"], result)
        self.assertIn("Turbo", result["query_understood"]["must_have"])
        car = result["cars"][0]

        self.assertEqual(car["brand"], "Porsche")
        self.assertEqual(car["model"], "911")
        self.assertIn("Turbo", car["pseudo_model"])

    async def test_continental_gt_alias_returns_bentley(self) -> None:
        car = await self._top("континенталь gt")

        self.assertEqual(car["brand"], "Bentley")
        self.assertEqual(car["model"], "Continental GT")

    async def test_urus_se_keeps_se_trim(self) -> None:
        car = await self._top("urus se")

        self.assertEqual(car["brand"], "Lamborghini")
        self.assertEqual(car["model"], "Urus")
        self.assertIn("SE", car["modification"])

    async def test_brake_feature_search_uses_description(self) -> None:
        result = await self.service.search("есть машины с керамическими тормозами?", {})

        self.assertTrue(result["found"], result)
        self.assertTrue(
            any("brakes" in car["matched_terms"] or "ceramic" in car["matched_terms"] for car in result["cars"]),
            result,
        )
        self.assertTrue(any(car["spec_highlights"] for car in result["cars"]), result)


if __name__ == "__main__":
    unittest.main()
