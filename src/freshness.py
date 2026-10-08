"""Decide whether derived outputs are current, by config content where possible.

File times alone can't tell a comment or metadata key in costs.yaml from a
weight change; on 2026-10-08 that made build_web drop correct routes. When
the cost surface records the fingerprint of the config it was built from
(`effective_config_sha256` in cost_surface_metadata.json, proposal C-20),
the config is compared by content and its file time is ignored. Without a
recorded fingerprint, the old file-time rule applies unchanged.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

FINGERPRINT_KEY = "effective_config_sha256"


def config_fingerprint(config: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON of a loaded config (same as export_model)."""
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def recorded_fingerprint(metadata_path: Path) -> str | None:
    try:
        value = json.loads(metadata_path.read_text(encoding="utf-8")).get(FINGERPRINT_KEY)
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and value else None


def stale_reasons(
    outputs: list[Path],
    inputs: list[Path],
    config_path: Path,
    config: dict[str, Any],
    metadata_paths: list[Path],
) -> list[str]:
    """Why the outputs are out of date; an empty list means current.

    `inputs` are compared by file time. The config is compared by content
    when every metadata file records a fingerprint, otherwise by file time.
    """
    reasons = []
    oldest_output = min(path.stat().st_mtime for path in outputs)
    for path in inputs:
        if path.stat().st_mtime > oldest_output:
            reasons.append(f"{path.name} is newer than the outputs")
    recorded = [recorded_fingerprint(path) for path in metadata_paths]
    if recorded and all(recorded):
        current = config_fingerprint(config)
        for path, value in zip(metadata_paths, recorded):
            if value != current:
                reasons.append(f"{path.name} was built from a different {config_path.name}")
    elif config_path.stat().st_mtime > oldest_output:
        reasons.append(f"{config_path.name} is newer than the outputs")
    return reasons
