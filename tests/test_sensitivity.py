import unittest

from shapely.geometry import LineString

from src import cost_surface
from validation import sensitivity


CONFIG = {
    "costs": {
        "open_land": 1,
        "road_major": 4,
        "urban_area": 8,
        "population": {"minimum": 1, "maximum": 10},
        "dwelling_proximity": {"max_distance_m": 200, "max_score": 6},
    }
}


class PerturbTests(unittest.TestCase):
    def test_scales_plain_and_dotted_keys_and_skips_missing(self) -> None:
        new, changed = sensitivity.perturb(
            CONFIG,
            ["road_major", "urban_area", "population.maximum",
             "dwelling_proximity.max_score", "not_a_key"],
            1.5,
        )
        self.assertEqual(new["costs"]["road_major"], 6)
        self.assertEqual(new["costs"]["urban_area"], 12)
        self.assertEqual(new["costs"]["population"]["maximum"], 15)
        self.assertEqual(new["costs"]["dwelling_proximity"]["max_score"], 9)
        self.assertNotIn("not_a_key", changed)
        self.assertEqual(CONFIG["costs"]["road_major"], 4)  # original untouched

    def test_clips_to_range_and_keeps_population_ordered(self) -> None:
        new, _ = sensitivity.perturb(CONFIG, ["population.maximum", "open_land"], 0.1)
        self.assertEqual(new["costs"]["open_land"], sensitivity.SCORE_RANGE[0])
        self.assertLessEqual(
            new["costs"]["population"]["minimum"], new["costs"]["population"]["maximum"]
        )


class RelaxedValidationTests(unittest.TestCase):
    def test_allows_scores_above_ten_only_inside_context(self) -> None:
        costs = {"open_land": 1, "open_sea": 2, "building_barrier": 10, "urban_area": 12,
                 "population": {"minimum": 1, "maximum": 15}}
        layers = {"urban": {"cost": "urban_area"}}
        with self.assertRaises(ValueError):
            cost_surface.validate_cost_scores(costs, layers, ["building_barrier"])
        with sensitivity.relaxed_score_validation():
            cost_surface.validate_cost_scores(costs, layers, ["building_barrier"])
            costs["urban_area"] = 40
            with self.assertRaises(ValueError):
                cost_surface.validate_cost_scores(costs, layers, ["building_barrier"])
        costs["urban_area"] = 12
        with self.assertRaises(ValueError):
            cost_surface.validate_cost_scores(costs, layers, ["building_barrier"])


class CompareTests(unittest.TestCase):
    def test_share_within_and_change_detection(self) -> None:
        base = LineString([(0, 0), (10_000, 0)])
        near = LineString([(0, 500), (10_000, 500)])
        far = LineString([(0, 3_000), (10_000, 3_000)])
        self.assertEqual(sensitivity.share_within(base, near, 1000), 1.0)
        self.assertEqual(sensitivity.share_within(base, far, 1000), 0.0)
        baseline = {"a": {"best": "x", "line": base}}
        scenario = {"a": {"best": "y", "line": near}}
        result = sensitivity.compare(baseline, scenario)
        self.assertEqual(result["best_changed"], 1)
        self.assertEqual(result["mean_route_within_1km"], 1.0)


if __name__ == "__main__":
    unittest.main()
