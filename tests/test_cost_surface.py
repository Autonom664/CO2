import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box
from shapely.geometry import box

from src.cost_surface import (
    population_costs,
    rasterize_layer,
    validate_cost_scores,
)
import src.cost_surface as cost_surface


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


class RasterizeLayerTests(unittest.TestCase):
    def test_empty_batch_ends_read_without_clearing_prior_burns(self) -> None:
        first_batch = gpd.GeoDataFrame(
            geometry=[box(0, 1, 1, 2)], crs="EPSG:25832"
        )
        empty_batch = gpd.GeoDataFrame(
            geometry=[], crs="EPSG:25832"
        )
        with (
            patch.object(
                cost_surface.pyogrio,
                "read_info",
                return_value={"features": 3},
            ),
            patch.object(
                cost_surface.pyogrio,
                "read_dataframe",
                side_effect=[first_batch, empty_batch],
            ) as read_dataframe,
        ):
            mask = rasterize_layer(
                gpkg=cost_surface.Path("unused.gpkg"),
                layer="synthetic",
                transform=from_origin(0, 2, 1, 1),
                width=2,
                height=2,
                all_touched=False,
                target_crs="EPSG:25832",
            )

        self.assertEqual(read_dataframe.call_count, 2)
        self.assertEqual(int(mask.sum()), 1)


class PopulationThresholdTests(unittest.TestCase):
    def test_cells_below_threshold_receive_no_population_cost(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raster_path = root / "population_2020_100m.tif"
            profile = {
                "driver": "GTiff",
                "height": 2,
                "width": 2,
                "count": 1,
                "dtype": "float32",
                "crs": "EPSG:25832",
                "transform": from_origin(500_000, 6_200_200, 100, 100),
                "nodata": -9999,
            }
            with rasterio.open(raster_path, "w", **profile) as dataset:
                dataset.write(
                    np.array([[0.5, 1], [2, 4]], dtype=np.float32), 1
                )
            with patch("src.cost_surface.PROCESSED", root):
                scores, summary = population_costs(
                    extent_mask=np.ones((2, 2), dtype=bool),
                    land_mask=np.ones((2, 2), dtype=bool),
                    transform=profile["transform"],
                    width=2,
                    height=2,
                    target_crs="EPSG:25832",
                    resolution_m=100,
                    settings={
                        "min_per_cell": 1,
                        "minimum": 1,
                        "maximum": 10,
                        "quantiles": 2,
                    },
                )

        self.assertEqual(float(scores[0, 0]), 0)
        self.assertGreater(float(scores[0, 1]), 0)
        self.assertEqual(summary["threshold_per_analysis_cell"], 1)


if __name__ == "__main__":
    unittest.main()
