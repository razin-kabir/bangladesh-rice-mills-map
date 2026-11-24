"""Paths and confidentiality settings for the rice-mill map.

Input data are never stored in this repository. By default they are read from
``data/`` (git-ignored); set the environment variables below to read them from
somewhere else instead. See ``data/README.md`` for the files that are needed.

    MATS_DATA_DIR    folder that contains ``miller_data/*.dta``
    BD_DISTRICT_SHP  path to the BBS 2022 district boundary shapefile
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Inputs (git-ignored) ─────────────────────────────────────────────────────
MATS_DIR = Path(os.environ.get("MATS_DATA_DIR", REPO_ROOT / "data" / "mats_2018"))
MILLER_DIR = MATS_DIR / "miller_data"
DISTRICT_SHP = Path(
    os.environ.get("BD_DISTRICT_SHP", REPO_ROOT / "data" / "shapefiles" / "district2022.shp")
)

# ── Outputs (committed) ──────────────────────────────────────────────────────
DOCS = REPO_ROOT / "docs"          # GitHub Pages site (interactive map)
FIGURES = REPO_ROOT / "figures"    # static maps

# ── Confidentiality rules ────────────────────────────────────────────────────
# Mill locations are never published. Mills are counted in hexagons HEX_KM wide;
# hexagons with fewer than MIN_MILLS mills are dropped, and capacity is reported
# only for hexagons with at least MIN_MILLS_CAPACITY mills (rounded).
HEX_KM = 20
MIN_MILLS = 3
MIN_MILLS_CAPACITY = 5
COORD_DECIMALS = 4                 # published polygon vertices (~11 m); grid geometry only

PROJECTED_CRS = "EPSG:32646"       # WGS 84 / UTM zone 46N (metres)
SURVEY_YEAR = 2018


def miller_file(name: str) -> Path:
    """Path to a MATS 2018 miller module, with a helpful error if it is missing."""
    path = MILLER_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. The MATS 2018 microdata are not distributed with "
            "this repository; see data/README.md for how to obtain them and point "
            "MATS_DATA_DIR at the folder that contains miller_data/."
        )
    return path
