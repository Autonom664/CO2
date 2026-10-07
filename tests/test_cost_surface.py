import unittest

from src.cost_surface import validate_cost_scores


class CostScoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.costs = {
            "open_land": 1,
            "open_sea": 2,
            "road_crossing": 3,
            "building_barrier": 10,
            "population": {"minimum": 1, "maximum": 10},
        }
        self.layers = {"roads": {"cost": "road_crossing"}}
        self.barriers = ["building_barrier"]

    def test_accepts_scores_within_one_to_ten(self) -> None:
        validate_cost_scores(self.costs, self.layers, self.barriers)

    def test_rejects_area_score_outside_one_to_ten(self) -> None:
        self.costs["road_crossing"] = 11
        with self.assertRaisesRegex(ValueError, "between 1 and 10"):
            validate_cost_scores(self.costs, self.layers, self.barriers)

    def test_rejects_population_score_outside_one_to_ten(self) -> None:
        self.costs["population"]["minimum"] = 0
        with self.assertRaisesRegex(ValueError, "between 1 and 10"):
            validate_cost_scores(self.costs, self.layers, self.barriers)

    def test_requires_buildings_to_remain_barriers(self) -> None:
        self.barriers = []
        with self.assertRaisesRegex(ValueError, "impassable barriers"):
            validate_cost_scores(self.costs, self.layers, self.barriers)


if __name__ == "__main__":
    unittest.main()
