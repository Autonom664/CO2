import tempfile
import unittest
from pathlib import Path

import yaml

from src.activate_p12 import activate_p12
from src.cost_surface import load_config


class P12ActivationTests(unittest.TestCase):
    def test_activation_archives_baseline_and_writes_merged_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline_path = root / "costs.yaml"
            overlay_path = root / "costs_p12.yaml"
            archived_path = root / "costs_baseline.yaml"
            baseline_path.write_text(
                "costs:\n  road_major: 4\n"
                "combine_groups:\n  protected:\n    members: [x, y]\n"
                "    rule: max\n",
                encoding="utf-8",
            )
            overlay_path.write_text(
                "extends: costs.yaml\n"
                "costs:\n  road_major: 5\n"
                "  landfall: 10\n"
                "replace_sections: [combine_groups]\n"
                "combine_groups:\n  people:\n    members: [urban, risk]\n"
                "    rule: max\n",
                encoding="utf-8",
            )

            activated = activate_p12(
                baseline_path, overlay_path, archived_path
            )

            self.assertEqual(
                baseline_path.read_text(encoding="utf-8"),
                yaml.safe_dump(activated, sort_keys=False, allow_unicode=True),
            )
            self.assertEqual(
                archived_path.read_text(encoding="utf-8"),
                "costs:\n  road_major: 4\n"
                "combine_groups:\n  protected:\n    members: [x, y]\n"
                "    rule: max\n",
            )
            self.assertNotIn("extends", load_config(baseline_path))
            self.assertEqual(activated["costs"]["road_major"], 5)
            self.assertEqual(activated["costs"]["landfall"], 10)
            self.assertEqual(set(activated["combine_groups"]), {"people"})

    def test_activation_refuses_to_overwrite_existing_baseline_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "costs.yaml"
            overlay = root / "costs_p12.yaml"
            archive = root / "costs_baseline.yaml"
            config.write_text("costs: {road_major: 4}\n", encoding="utf-8")
            overlay.write_text(
                "extends: costs.yaml\ncosts: {road_major: 5}\n",
                encoding="utf-8",
            )
            archive.write_text("existing baseline\n", encoding="utf-8")

            with self.assertRaisesRegex(FileExistsError, "Refusing to overwrite"):
                activate_p12(config, overlay, archive)

            self.assertEqual(
                config.read_text(encoding="utf-8"), "costs: {road_major: 4}\n"
            )
            self.assertEqual(
                archive.read_text(encoding="utf-8"), "existing baseline\n"
            )


if __name__ == "__main__":
    unittest.main()
