"""Activate the P12 cost model after the C14 baseline has been recorded."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml

from src.cost_surface import CONFIG, load_config


ROOT = Path(__file__).resolve().parents[1]
P12_CONFIG = ROOT / "config" / "costs_p12.yaml"
BASELINE_CONFIG = ROOT / "config" / "costs_baseline.yaml"


def activate_p12(
    config_path: Path = CONFIG,
    overlay_path: Path = P12_CONFIG,
    baseline_path: Path = BASELINE_CONFIG,
) -> dict[str, Any]:
    if baseline_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing baseline config: {baseline_path}"
        )

    merged_config = load_config(overlay_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            yaml.safe_dump(
                merged_config,
                stream,
                sort_keys=False,
                allow_unicode=True,
            )
        shutil.copy2(config_path, baseline_path)
        os.replace(temporary_path, config_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return merged_config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replace costs.yaml with the merged P12 model after C14."
    )
    parser.add_argument(
        "--c14-confirmed",
        action="store_true",
        help="Confirm Claude's C14 baseline has been recorded.",
    )
    args = parser.parse_args()
    if not args.c14_confirmed:
        parser.error(
            "P12 activation is blocked until C14 is recorded; "
            "pass --c14-confirmed only after confirmation."
        )
    activate_p12()


if __name__ == "__main__":
    main()
