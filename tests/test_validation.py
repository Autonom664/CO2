import unittest

from shapely.geometry import LineString, MultiLineString

from validation import baltic_pipe


class CompareLinesTests(unittest.TestCase):
    def test_identical_lines_have_zero_offset(self) -> None:
        line = LineString([(0, 0), (10_000, 0)])
        stats = baltic_pipe.compare_lines(line, line)
        self.assertEqual(stats["mean_offset_km"], 0)
        self.assertEqual(stats["length_ratio"], 1)
        self.assertEqual(stats["share_model_within_1km"], 1)

    def test_parallel_offset_and_detour(self) -> None:
        reference = LineString([(0, 0), (10_000, 0)])
        model = LineString([(0, 2_000), (10_000, 2_000)])
        stats = baltic_pipe.compare_lines(model, reference)
        self.assertAlmostEqual(stats["median_offset_km"], 2.0)
        self.assertEqual(stats["share_model_within_1km"], 0)
        self.assertEqual(stats["share_model_within_5km"], 1)

    def test_gapped_reference_and_far_ends(self) -> None:
        reference = MultiLineString(
            [[(0, 0), (4_000, 0)], [(6_000, 0), (10_000, 0)]]
        )
        model = LineString([(0, 0), (10_000, 0)])
        stats = baltic_pipe.compare_lines(model, reference)
        self.assertEqual(stats["reference_km"], 8.0)
        self.assertEqual(stats["share_reference_within_5km_of_model"], 1)
        start, end = baltic_pipe.endpoints(reference)
        self.assertEqual({start[0], end[0]}, {0.0, 10_000.0})


if __name__ == "__main__":
    unittest.main()
