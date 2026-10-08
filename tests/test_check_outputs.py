import unittest

from shapely.geometry import Point

from validation import check_outputs


HOTSPOTS = [
    {"id": "a", "role": "source"},
    {"id": "b", "role": "source"},
    {"id": "x", "role": "storage"},
    {"id": "y", "role": "storage"},
]


def route(a, b, **extra):
    return {"from_id": a, "to_id": b, "length_km": 10.0, "accumulated_cost": 5.0} | extra


class RouteSetTests(unittest.TestCase):
    def test_complete_set_passes(self) -> None:
        routes = [route(a, b) for a in "ab" for b in "xy"]
        self.assertEqual(check_outputs.check_route_set(HOTSPOTS, routes), [])

    def test_missing_duplicate_reversed_and_bad_values(self) -> None:
        routes = [
            route("a", "x"), route("a", "x"), route("x", "b"),
            route("b", "y", accumulated_cost=float("inf"), km_open_sea=12.0),
        ]
        problems = " | ".join(check_outputs.check_route_set(HOTSPOTS, routes))
        self.assertIn("duplicate", problems)
        self.assertIn("missing", problems)
        self.assertIn("wrong direction", problems)
        self.assertIn("not positive", problems)
        self.assertIn("km_open_sea", problems)


class TreeTests(unittest.TestCase):
    ids = ["a", "b", "x", "y"]

    def test_spanning_tree_passes(self) -> None:
        self.assertEqual(
            check_outputs.check_tree(self.ids, [("a", "x"), ("b", "x"), ("y", "a")]),
            [],
        )

    def test_cycle_and_disconnected(self) -> None:
        problems = " | ".join(
            check_outputs.check_tree(self.ids, [("a", "x"), ("x", "a"), ("b", "y")])
        )
        self.assertIn("cycle", problems)
        self.assertIn("disconnected", problems)


class LengthTests(unittest.TestCase):
    def test_route_shorter_than_straight_line_fails(self) -> None:
        points = {"a": Point(0, 0), "x": Point(20_000, 0)}
        self.assertEqual(
            check_outputs.check_lengths(points, [route("a", "x", length_km=21)], 1), []
        )
        self.assertTrue(
            check_outputs.check_lengths(points, [route("a", "x", length_km=12)], 1)
        )


class DetourTests(unittest.TestCase):
    def test_detour_factor_is_length_over_straight_line(self) -> None:
        points = {"a": Point(0, 0), "x": Point(10_000, 0)}
        factors = check_outputs.detour_factors(points, [route("a", "x", length_km=12)])
        self.assertAlmostEqual(factors["a→x"], 1.2)


if __name__ == "__main__":
    unittest.main()
