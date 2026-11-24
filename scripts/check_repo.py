#!/usr/bin/env python3
"""Pre-publication privacy checks. Standard library only; exits 1 on any failure.

Checks every file git would publish (tracked files plus untracked, non-ignored
files) for:
  * survey microdata / GIS files (by extension)
  * Jupyter notebooks that contain outputs or execution counts
  * references to directly identifying MATS variables (names, addresses,
    interviewer, interview-location GPS, questionnaire number)
  * local absolute paths, e-mail addresses, Bangladeshi phone numbers and
    high-precision coordinates
  * files larger than 10 MB
and audits the data embedded in the published web map (docs/index.html):
  * no point geometries anywhere
  * every published cell is a hexagon with at least MIN_MILLS mills
  * capacity only for cells with at least MIN_MILLS_CAPACITY mills
  * no coordinate more precise than COORD_DECIMALS
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DATA_EXT = {
    ".dta", ".rdata", ".rds", ".sav", ".csv", ".tsv", ".xls", ".xlsx", ".parquet",
    ".feather", ".pkl", ".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx",
    ".gpkg", ".geojson", ".kml", ".kmz", ".zip", ".7z", ".gz",
}
TEXT_EXT = {".py", ".ipynb", ".tex", ".bib", ".md", ".toml", ".cff", ".yml", ".yaml",
            ".txt", ".cfg", ".sha256", ".html", ".css", ".js", ""}
# a01 name, a06 union/ward, a07 village/street, a08 interviewer, a10_* interview-
# location GPS, q_no questionnaire no., b00* respondent name/address, b02 gender.
IDENTIFYING_VARS = re.compile(r"""["'](a01|a06|a07|a08|a10_\w+|q_no|b00\w*|b02)["']""")
ALLOWED_EMAILS: set[str] = set()
PATTERNS = {
    "local absolute path": re.compile(r"(/Users/|/home/[a-z]|[A-Za-z]:\\\\?Users|Dropbox)"),
    "phone number": re.compile(r"(?<!\d)(?:\+?880[- ]?|0)1[3-9]\d{2}[- ]?\d{6}(?!\d)"),
    "high-precision coordinate": re.compile(r"(?<![\d.])(2[0-6]\.\d{5,}|(8[89]|9[0-2])\.\d{5,})"),
    "e-mail address": re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z][\w.-]*"),
}
MAX_BYTES = 10 * 1024 * 1024
CELL_KEYS = {"id", "n", "division", "husking", "semi_auto", "automatic", "own_sole",
             "own_partners", "own_sole_rented", "own_partners_rented", "capacity",
             "districts"}


def publishable_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode()
    return [ROOT / p for p in out.split("\0") if p and (ROOT / p).is_file()]


def setting(name: str) -> int:
    m = re.search(rf"^{name}\s*=\s*(\d+)", (ROOT / "analysis" / "common.py").read_text(), re.M)
    if not m:
        raise SystemExit(f"cannot read {name} from analysis/common.py")
    return int(m.group(1))


def geometry_types(obj, out):
    if isinstance(obj, dict):
        if obj.get("type") in {"Point", "MultiPoint", "LineString", "MultiLineString",
                               "Polygon", "MultiPolygon", "GeometryCollection"}:
            out.add(obj["type"])
        for v in obj.values():
            geometry_types(v, out)
    elif isinstance(obj, list):
        for v in obj:
            geometry_types(v, out)


def coord_numbers(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from (coord_numbers(v) if k != "coordinates" else _flatten(v))
    elif isinstance(obj, list):
        for v in obj:
            yield from coord_numbers(v)


def _flatten(v):
    if isinstance(v, list):
        for x in v:
            yield from _flatten(x)
    else:
        yield v


def _reject_constant(name: str):
    raise ValueError(f"non-JSON constant {name}")   # NaN / Infinity are not valid JSON


def audit_webmap(path: Path) -> list[str]:
    problems = []
    text = path.read_text(encoding="utf-8")
    m = re.search(r"const DATA = (\{.*?\});\n\(function", text, re.S)
    if not m:
        return [f"{path.name}: could not find embedded DATA"]
    try:
        data = json.loads(m.group(1), parse_constant=_reject_constant)
    except ValueError as e:
        return [f"{path.name}: embedded DATA is not strict JSON ({e})"]
    min_mills, min_cap, decimals = (setting("MIN_MILLS"), setting("MIN_MILLS_CAPACITY"),
                                    setting("COORD_DECIMALS"))
    types: set[str] = set()
    geometry_types(data, types)
    if types & {"Point", "MultiPoint"}:
        problems.append(f"{path.name}: contains point geometries")
    for f in data["cells"]["features"]:
        p, g = f["properties"], f["geometry"]
        tag = f"{path.name}: cell {p.get('id')}"
        if set(p) - CELL_KEYS:
            problems.append(f"{tag}: unexpected properties {sorted(set(p) - CELL_KEYS)}")
        if g["type"] != "Polygon" or len(g["coordinates"]) != 1 or len(g["coordinates"][0]) != 7:
            problems.append(f"{tag}: not a hexagon")
        if p["n"] < min_mills:
            problems.append(f"{tag}: {p['n']} mills < MIN_MILLS={min_mills}")
        if p.get("capacity") is not None and p["n"] < min_cap:
            problems.append(f"{tag}: capacity shown with {p['n']} mills < {min_cap}")
    too_precise = [x for x in coord_numbers(data)
                   if isinstance(x, float) and len(repr(x).split(".")[-1]) > decimals]
    if too_precise:
        problems.append(f"{path.name}: {len(too_precise)} coordinates with > {decimals} decimals")
    return problems


def main() -> int:
    problems: list[str] = []
    files = publishable_files()
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if rel == "scripts/check_repo.py":
            continue  # contains the patterns themselves
        ext = path.suffix.lower()
        if ext in DATA_EXT:
            problems.append(f"{rel}: data/GIS file must not be published")
            continue
        if path.stat().st_size > MAX_BYTES:
            problems.append(f"{rel}: larger than 10 MB")
        if ext not in TEXT_EXT and path.name not in {"Makefile", "LICENSE", ".gitignore"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if ext == ".ipynb":
            nb = json.loads(text)
            for i, cell in enumerate(nb.get("cells", [])):
                if cell.get("cell_type") == "code" and (cell.get("outputs") or cell.get("execution_count")):
                    problems.append(f"{rel}: cell {i} has outputs (clear all outputs before committing)")
        if rel == "docs/index.html":
            problems += audit_webmap(path)
        for m in IDENTIFYING_VARS.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            problems.append(f"{rel}:{line}: references identifying survey variable {m.group(1)}")
        for name, pat in PATTERNS.items():
            for m in pat.finditer(text):
                hit = m.group(0)
                if name == "e-mail address" and (hit.lower() in ALLOWED_EMAILS
                                                 or hit.lower().endswith("users.noreply.github.com")):
                    continue
                line = text.count("\n", 0, m.start()) + 1
                problems.append(f"{rel}:{line}: {name}: {hit!r}")

    if problems:
        print("Privacy check FAILED:")
        for p in problems:
            print("  -", p)
        return 1
    print(f"Privacy check passed ({len(files)} files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
