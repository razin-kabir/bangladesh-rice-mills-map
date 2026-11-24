"""Aggregate MATS 2018 rice-mill locations to a hexagon grid and draw the maps.

Exact mill locations are confidential. They are read only to assign each mill
to a hexagon (``HEX_KM`` wide); nothing below that level is ever written out.
"""
from __future__ import annotations

import json
import math
import textwrap
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Polygon, box, mapping

from common import (COORD_DECIMALS, DISTRICT_SHP, HEX_KM, MIN_MILLS, MIN_MILLS_CAPACITY,
                    PROJECTED_CRS, REPO_ROOT, SURVEY_YEAR, miller_file)

MILL_TYPES = {"husking": "Husking mill", "semi_auto": "Semi-automatic mill",
              "automatic": "Automatic mill"}
OWNERSHIP = {"own_sole": "Sole ownership", "own_partners": "Owned by partners",
             "own_sole_rented": "Sole rented", "own_partners_rented": "Rented by partners"}
# Survey spellings -> BBS 2022 spellings used by the boundary file
DIVISION_NAMES = {"Barisal": "Barishal", "Chittagong": "Chattogram"}

# Viridis, reversed so that lighter = fewer mills and darker = more, in BOTH themes.
# Sampled at 0.93, 0.72, 0.50, 0.30, 0.12: trimming the extremes keeps the lightest
# step visible on light maps and the darkest on dark maps (hexagons are also outlined).
RAMP = ["#d2e21b", "#4ec36b", "#21918c", "#355f8d", "#472a7a"]
RAMP_LIGHT = RAMP_DARK = RAMP
BINS_TOTAL = [3, 5, 7, 10, 15]     # all mills: 3-4, 5-6, 7-9, 10-14, 15+
BINS_PART = [1, 2, 4, 7, 10]       # one type/ownership: 1, 2-3, 4-6, 7-9, 10+
INK = {"primary": "#0b0b0b", "secondary": "#52514e", "muted": "#898781",
       "land": "#f0efec", "edge": "#c3c2b7", "surface": "#fcfcfb"}


# ── Data ──────────────────────────────────────────────────────────────────────
def load_mills() -> pd.DataFrame:
    """One row per surveyed mill: GPS, division, 2018 mill type, ownership and capacity.

    Only the columns listed here are read. Names, addresses, interviewer and
    other identifying fields in the same files are never loaded.
    """
    a = pd.read_stata(miller_file("miller_ModA.dta"),
                      columns=["a02", "a03", "a10latitude", "a10longitude"])
    c1 = pd.read_stata(miller_file("miller_ModC.Sec1.dta"), columns=["a02", "c03", "c05"])
    c4 = pd.read_stata(miller_file("miller_ModC.Sec4_6.dta"),
                       columns=["a02", "year", "milling_capacity"])
    cap = c4.loc[c4["year"].astype(str) == str(SURVEY_YEAR), ["a02", "milling_capacity"]]
    assert cap["a02"].is_unique and c1["a02"].is_unique and a["a02"].is_unique

    df = a.merge(c1, on="a02", how="left").merge(cap, on="a02", how="left")
    return pd.DataFrame({
        "lat": pd.to_numeric(df["a10latitude"], errors="coerce"),
        "lon": pd.to_numeric(df["a10longitude"], errors="coerce"),
        "division": df["a03"].astype(str).replace(DIVISION_NAMES),
        "mill_type": df["c05"].astype(str),        # type of mill in 2018
        "ownership": df["c03"].astype(str),        # ownership at start of reported history
        "capacity": pd.to_numeric(df["milling_capacity"], errors="coerce"),  # MT per fortnight
    })


def load_boundaries():
    """District polygons (WGS 84) and the national outline (projected, gaps closed)."""
    if not DISTRICT_SHP.exists():
        raise FileNotFoundError(f"{DISTRICT_SHP} not found. See data/README.md.")
    districts = gpd.read_file(DISTRICT_SHP)[["DIVISION_N", "DISTRICT_N", "geometry"]]
    districts = districts.to_crs(PROJECTED_CRS)
    country = districts.union_all().buffer(15)    # closes slivers between districts
    return districts, country


def locate(mills: pd.DataFrame, country, tolerance_m: float = 1000):
    """Project mills with valid GPS inside Bangladesh; raw coordinates are dropped."""
    has_gps = mills["lat"].notna() & mills["lon"].notna()
    pts = gpd.GeoDataFrame(
        mills.loc[has_gps].drop(columns=["lat", "lon"]),
        geometry=gpd.points_from_xy(mills.loc[has_gps, "lon"], mills.loc[has_gps, "lat"]),
        crs="EPSG:4326",
    ).to_crs(PROJECTED_CRS)
    inside = pts.within(country.buffer(tolerance_m))
    excluded = {"no_gps": int((~has_gps).sum()), "outside_bangladesh": int((~inside).sum())}
    return pts[inside].reset_index(drop=True), excluded


# ── Hexagon grid (pointy-top, axial coordinates, metres) ─────────────────────
def _circumradius() -> float:
    return HEX_KM * 1000 / math.sqrt(3)            # HEX_KM = flat-to-flat width


def hex_index(x: np.ndarray, y: np.ndarray):
    """Axial (q, r) of the hexagon containing each projected point."""
    s = _circumradius()
    q = (math.sqrt(3) / 3 * x - y / 3) / s
    r = (2 / 3 * y) / s
    c = -q - r
    rq, rr, rc = np.round(q), np.round(r), np.round(c)
    dq, dr, dc = np.abs(rq - q), np.abs(rr - r), np.abs(rc - c)
    fix_q = (dq > dr) & (dq > dc)
    fix_r = ~fix_q & (dr >= dc)
    rq = np.where(fix_q, -rr - rc, rq)
    rr = np.where(fix_r, -rq - rc, rr)
    return rq.astype(int), rr.astype(int)


def hex_polygon(q: int, r: int) -> Polygon:
    s = _circumradius()
    cx, cy = s * math.sqrt(3) * (q + r / 2), s * 1.5 * r
    return Polygon([(cx + s * math.cos(math.radians(30 + 60 * i)),
                     cy + s * math.sin(math.radians(30 + 60 * i))) for i in range(6)])


def round_sig(x: float, sig: int = 2) -> int:
    """Round to ``sig`` significant figures (e.g. 135 -> 140)."""
    digits = sig - 1 - int(math.floor(math.log10(abs(x))))
    return int(round(x, digits))


def aggregate(mills: gpd.GeoDataFrame):
    """Count mills per hexagon; drop hexagons below MIN_MILLS. Returns (cells, summary)."""
    q, r = hex_index(mills.geometry.x.to_numpy(), mills.geometry.y.to_numpy())
    # Self-check: every mill lies inside the hexagon it is counted in
    polys = np.array([hex_polygon(a, b) for a, b in zip(q, r)])
    assert shapely.covers(shapely.buffer(polys, 1e-6), mills.geometry.to_numpy()).all()

    mills = mills.assign(q=q, r=r)
    rows = []
    for (qq, rr), g in mills.groupby(["q", "r"]):
        n = len(g)
        if n < MIN_MILLS:
            continue
        top = g["division"].value_counts()
        row = {"q": int(qq), "r": int(rr), "n": n,
               "division": sorted(top[top == top.max()].index)[0]}   # majority division
        row.update({k: int((g["mill_type"] == v).sum()) for k, v in MILL_TYPES.items()})
        row.update({k: int((g["ownership"] == v).sum()) for k, v in OWNERSHIP.items()})
        caps = g["capacity"].dropna()
        row["capacity"] = round_sig(caps.median()) if len(caps) >= MIN_MILLS_CAPACITY else None
        rows.append(row)

    cells = gpd.GeoDataFrame(rows, geometry=[hex_polygon(c["q"], c["r"]) for c in rows],
                             crs=PROJECTED_CRS)
    cy, cx = cells.geometry.centroid.y, cells.geometry.centroid.x
    cells = cells.iloc[np.lexsort((cx.to_numpy(), -cy.to_numpy()))].reset_index(drop=True)
    cells.insert(0, "id", np.arange(1, len(cells) + 1))          # numbered north to south
    cells = cells.drop(columns=["q", "r"])
    summary = {"mills": len(mills), "cells": len(cells), "mills_shown": int(cells["n"].sum()),
               "mills_hidden": int(len(mills) - cells["n"].sum()),
               "hex_km": HEX_KM, "min_mills": MIN_MILLS, "min_mills_capacity": MIN_MILLS_CAPACITY}
    return cells, summary


def add_district_names(cells: gpd.GeoDataFrame, districts: gpd.GeoDataFrame,
                       min_share: float = 0.05) -> gpd.GeoDataFrame:
    """Name the districts covering at least ``min_share`` of each hexagon (largest first)."""
    names = []
    for hexagon in cells.geometry:
        share = districts.geometry.intersection(hexagon).area / hexagon.area
        top = share[share >= min_share].sort_values(ascending=False)
        names.append(", ".join(districts.loc[top.index, "DISTRICT_N"]))
    return cells.assign(districts=names)


# ── GeoJSON helpers ──────────────────────────────────────────────────────────
def _round(obj, nd=COORD_DECIMALS):
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, (list, tuple)):
        return [_round(v, nd) for v in obj]
    return obj


def _clean(v):
    """JSON-safe property value: NaN -> None, whole floats -> int."""
    if isinstance(v, float):
        if math.isnan(v):
            return None
        if v.is_integer():
            return int(v)
    return v


def _feature_collection(gdf: gpd.GeoDataFrame, props: list[str]) -> dict:
    gdf = gdf.to_crs("EPSG:4326")
    feats = []
    for rec, geom in zip(gdf[props].to_dict("records"), gdf.geometry):
        rec = {k: _clean(v) for k, v in rec.items()}
        g = mapping(geom)
        feats.append({"type": "Feature", "properties": rec,
                      "geometry": {"type": g["type"], "coordinates": _round(g["coordinates"])}})
    return {"type": "FeatureCollection", "features": feats}


def _geometry(geom, crs=PROJECTED_CRS) -> dict:
    g = mapping(gpd.GeoSeries([geom], crs=crs).to_crs("EPSG:4326").iloc[0])
    return {"type": g["type"], "coordinates": _round(g["coordinates"])}


# ── Interactive web map ──────────────────────────────────────────────────────
def write_webmap(cells, districts, country, summary, excluded, path: Path) -> None:
    try:   # simplify shared edges once, so neighbouring districts stay gap-free
        simple = shapely.coverage_simplify(districts.geometry.to_numpy(), 300)
    except Exception:
        simple = districts.geometry.simplify(300).to_numpy()
    simple_districts = districts.assign(geometry=simple)
    outline = country.simplify(300)
    lon0, lat0, lon1, lat1 = gpd.GeoSeries([country], crs=PROJECTED_CRS).to_crs(4326).total_bounds
    data = {
        "cells": _feature_collection(cells, [c for c in cells.columns if c != "geometry"]),
        "districts": _feature_collection(simple_districts, ["DISTRICT_N"]),
        "outline": _geometry(outline),
        # world minus Bangladesh: dims neighbouring countries on the basemap
        "mask": _geometry(box(-180, -85, 180, 85).difference(
            gpd.GeoSeries([outline], crs=PROJECTED_CRS).to_crs(4326).iloc[0]), crs="EPSG:4326"),
        "bounds": _round([[float(lat0), float(lon0)], [float(lat1), float(lon1)]]),
        "summary": {**summary, **excluded, "excluded_text": exclusion_text(excluded)},
        "labels": {"types": [list(kv) for kv in MILL_TYPES.items()],   # lists keep order
                   "ownership": [list(kv) for kv in OWNERSHIP.items()]},
        "bins": {"total": BINS_TOTAL, "part": BINS_PART},
        "ramp": {"light": RAMP_LIGHT, "dark": RAMP_DARK},
    }
    template = (REPO_ROOT / "analysis" / "webmap_template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False)   # strict JSON: fails loudly on NaN
    assert template.count("/*__DATA__*/null") == 1
    html = template.replace("/*__DATA__*/null", payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    print(f"Wrote {path.relative_to(REPO_ROOT)} ({path.stat().st_size / 1e3:.0f} kB)")


# ── Static maps ──────────────────────────────────────────────────────────────
def _bin_labels(bins):
    out = []
    for i, lo in enumerate(bins):
        if i == len(bins) - 1:
            out.append(f"{lo}+")
        else:
            hi = bins[i + 1] - 1
            out.append(f"{lo}" if hi == lo else f"{lo}–{hi}")
    return out


def _colors(values, bins):
    idx = np.searchsorted(bins, values, side="right") - 1
    return [RAMP_LIGHT[i] if v >= bins[0] else None for v, i in zip(values, idx)]


def _base(ax, districts, country):
    ax.set_facecolor(INK["surface"])
    districts.plot(ax=ax, color=INK["land"], edgecolor=INK["edge"], linewidth=0.35, zorder=1)
    gpd.GeoSeries([country], crs=PROJECTED_CRS).boundary.plot(
        ax=ax, color=INK["secondary"], linewidth=0.7, zorder=4)
    xmin, ymin, xmax, ymax = country.bounds
    pad = 15000
    ax.set_xlim(xmin - pad, xmax + pad)
    ax.set_ylim(ymin - pad, ymax + pad)
    ax.set_aspect("equal")
    ax.axis("off")


def _hexes(ax, cells, column, bins):
    cols = _colors(cells[column].to_numpy(), bins)
    shown = [c is not None for c in cols]
    cells[shown].plot(ax=ax, color=[c for c in cols if c], edgecolor=INK["secondary"],
                      linewidth=0.45, zorder=3)
    empty = cells[[not s for s in shown]]
    if len(empty):
        empty.plot(ax=ax, facecolor="none", edgecolor=INK["muted"], linewidth=0.5, zorder=3)


def _legend(ax, bins, title, extra=None, loc="lower left"):
    handles = [mpatches.Patch(facecolor=c, edgecolor=INK["surface"], label=l)
               for c, l in zip(RAMP_LIGHT, _bin_labels(bins))]
    if extra:
        handles.append(mpatches.Patch(facecolor="none", edgecolor=INK["muted"], label=extra))
    leg = ax.legend(handles=handles, title=title, loc=loc, frameon=False, fontsize=8.5,
                    title_fontsize=9, alignment="left")
    for t in leg.get_texts():
        t.set_color(INK["secondary"])
    leg.get_title().set_color(INK["primary"])


def exclusion_text(excluded) -> str:
    """e.g. '1 mill without GPS coordinates excluded.' ('' if nothing was excluded)."""
    def n_mills(n):
        return f"{n} mill{'s' if n != 1 else ''}"
    parts = []
    if excluded["no_gps"]:
        parts.append(f"{n_mills(excluded['no_gps'])} without GPS coordinates")
    if excluded["outside_bangladesh"]:
        parts.append(f"{n_mills(excluded['outside_bangladesh'])} with GPS outside Bangladesh")
    return (" and ".join(parts) + " excluded.") if parts else ""


def _note(fig, summary, excluded, width):
    text = (f"Each hexagon is {HEX_KM} km across. To protect respondent confidentiality, "
            f"hexagons with fewer than {MIN_MILLS} surveyed mills are not shown "
            f"({summary['mills_hidden']} of {summary['mills']} mapped mills). "
            f"{exclusion_text(excluded)} Source: Bangladesh Millers and Traders Survey (MATS) "
            "2018, IFPRI. Boundaries: Bangladesh Bureau of Statistics (BBS), 2022.")
    fig.text(0.02, 0.012, textwrap.fill(text, width), fontsize=7.5, color=INK["muted"],
             ha="left", va="bottom", linespacing=1.4)


def draw_total(cells, districts, country, summary, excluded, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 10.2))
    _base(ax, districts, country)
    _hexes(ax, cells, "n", BINS_TOTAL)
    _legend(ax, BINS_TOTAL, "Surveyed mills\nper hexagon")
    fig.text(0.02, 0.975, "Surveyed rice mills, Bangladesh 2018", fontsize=15,
             fontweight="bold", color=INK["primary"], va="top")
    fig.text(0.02, 0.945, f"Number of mills per {HEX_KM} km hexagon "
             f"({summary['mills_shown']} mills in {summary['cells']} hexagons)",
             fontsize=10, color=INK["secondary"], va="top")
    _note(fig, summary, excluded, width=125)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.93, bottom=0.06)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200, facecolor=INK["surface"], metadata={"Software": None})
    plt.close(fig)
    print(f"Wrote {path.relative_to(REPO_ROOT)}")


def draw_by_type(cells, districts, country, summary, excluded, path: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(13, 6.6))
    for ax, (key, label) in zip(axes, MILL_TYPES.items()):
        _base(ax, districts, country)
        _hexes(ax, cells, key, BINS_PART)
        ax.set_title(f"{label}s  ({int(cells[key].sum())} in shown hexagons)", fontsize=11,
                     color=INK["primary"], loc="left")
    handles = [mpatches.Patch(facecolor=c, edgecolor=INK["surface"], label=l)
               for c, l in zip(RAMP_LIGHT, _bin_labels(BINS_PART))]
    handles.append(mpatches.Patch(facecolor="none", edgecolor=INK["muted"], label="None of this type"))
    leg = fig.legend(handles=handles, title="Mills of this type per hexagon", ncol=len(handles),
                     loc="lower center", bbox_to_anchor=(0.5, 0.075), frameon=False,
                     fontsize=9, title_fontsize=9.5)
    for t in leg.get_texts():
        t.set_color(INK["secondary"])
    fig.text(0.01, 0.975, "Surveyed rice mills by type, Bangladesh 2018", fontsize=14,
             fontweight="bold", color=INK["primary"], va="top")
    _note(fig, summary, excluded, width=200)
    fig.subplots_adjust(left=0.005, right=0.995, top=0.87, bottom=0.17, wspace=0.02)
    fig.savefig(path, dpi=200, facecolor=INK["surface"], metadata={"Software": None})
    plt.close(fig)
    print(f"Wrote {path.relative_to(REPO_ROOT)}")
