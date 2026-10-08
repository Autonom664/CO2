import io
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point

from validation import check_starter_kit as kit_check

CONFIG = {"layers": {"wetlands": {}, "bnbo": {}}}
GUIDE = 'Use "land.tif", "sea.tif", "l_wetlands.tif" and "l_bnbo.tif", plus "population.tif".'


def write_tif(path: Path, array: np.ndarray, transform) -> None:
    profile = {"driver": "GTiff", "width": array.shape[1], "height": array.shape[0], "count": 1,
               "dtype": array.dtype.name, "crs": "EPSG:25832", "transform": transform}
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(array, 1)


class StarterKitCheckTests(unittest.TestCase):
    def build(self, root: Path, *, shift_bnbo: bool = False, bad_values: bool = False) -> Path:
        transform = from_origin(440000, 6400000, 100, 100)
        write_tif(root / "reference.tif", np.ones((4, 5), dtype=np.float32), transform)
        kit = root / "kit"
        (kit / "rasters").mkdir(parents=True)
        mask = np.zeros((4, 5), dtype=np.uint8)
        mask[1, 2] = 2 if bad_values else 1
        for name in ("land", "sea", "l_wetlands"):
            write_tif(kit / "rasters" / f"{name}.tif", mask, transform)
        write_tif(kit / "rasters" / "l_bnbo.tif", mask,
                  from_origin(440050, 6400000, 100, 100) if shift_bnbo else transform)
        write_tif(kit / "rasters" / "population.tif", np.full((4, 5), 3.5, dtype=np.float32), transform)
        gdb = kit / "co2_routing.gdb"
        sites = gpd.GeoDataFrame({"id": ["a", "b"], "name": ["A", "B"], "role": ["source", "storage"]},
                                 geometry=[Point(440150, 6399850), Point(440350, 6399750)], crs="EPSG:25832")
        for layer in kit_check.GDB_LAYERS:
            sites.to_file(gdb, layer=layer, driver="OpenFileGDB")
        (kit / "weights.csv").write_text(
            "layer,raster,cost_key,weight,treatment,group,surface\n"
            "wetlands,l_wetlands.tif,wetland,1,cost,wet_nature,land\n"
            "bnbo,l_bnbo.tif,protected_barrier,,barrier,,any\n", encoding="utf-8")
        (kit / "README.txt").write_text(
            "Research and teaching tool, provided as is; not engineering or permitting advice.\n"
            "Unzip into a NEW, EMPTY folder and back up your ArcGIS project first. See DISCLAIMER.\n",
            encoding="utf-8")
        (kit / "DISCLAIMER.md").write_text("# Disclaimer\n", encoding="utf-8")
        archive = root / "kit.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for path in kit.rglob("*"):
                if path.is_file():
                    zf.write(path, Path("co2_arcgis_starter_kit") / path.relative_to(kit))
        return archive

    def run_check(self, archive: Path, reference: Path) -> tuple[int, str]:
        out = io.StringIO()
        with (patch.object(kit_check, "REFERENCE", reference),
              patch.object(kit_check, "GUIDE", reference.parent / "guide.md"),
              patch.object(kit_check.cost_surface, "load_config", lambda _: CONFIG),
              patch("sys.argv", ["check", str(archive)]),
              redirect_stdout(out)):
            (reference.parent / "guide.md").write_text(GUIDE, encoding="utf-8")
            with patch.object(kit_check.sys.stdout, "reconfigure", create=True):
                code = kit_check.main()
        return code, out.getvalue()

    def test_a_correct_kit_passes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            code, output = self.run_check(self.build(root), root / "reference.tif")
        self.assertEqual(code, 0, output)
        self.assertIn("Starter kit OK", output)

    def test_misaligned_raster_and_non_binary_mask_fail(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            code, output = self.run_check(self.build(root, shift_bnbo=True, bad_values=True), root / "reference.tif")
        self.assertEqual(code, 1)
        self.assertIn("FAIL  all rasters on the 100 m analysis grid", output)
        self.assertIn("l_bnbo.tif", output)
        self.assertIn("FAIL  mask rasters contain only 0 and 1", output)

    def test_missing_safety_notice_and_disclaimer_fail(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = self.build(root)
            with zipfile.ZipFile(archive) as zf:
                kept = {n: zf.read(n) for n in zf.namelist() if not n.endswith("DISCLAIMER.md")}
            kept["co2_arcgis_starter_kit/README.txt"] = b"Just data."
            with zipfile.ZipFile(archive, "w") as zf:
                for name, data in kept.items():
                    zf.writestr(name, data)
            code, output = self.run_check(archive, root / "reference.tif")
        self.assertEqual(code, 1)
        self.assertIn("lacks", output)
        self.assertIn("DISCLAIMER.md is missing", output)


if __name__ == "__main__":
    unittest.main()
