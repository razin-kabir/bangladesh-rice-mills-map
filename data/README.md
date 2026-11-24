# Input data (not included)

Nothing in this folder except this file and `checksums.sha256` is tracked by git.

## 1. MATS 2018 miller survey

The 2018 Bangladesh Millers and Traders Survey (MATS) was conducted by the International Food
Policy Research Institute (IFPRI). The microdata are **not publicly released**. They contain
direct identifiers (respondent names, union/village, interviewer) and the exact GPS location of
every mill. To request access, contact the author or IFPRI.

The maps need three miller modules. Only the columns listed are read:

| File | Variables read | Used for |
|---|---|---|
| `miller_ModA.dta` | `a02` (mill ID), `a03` (division), `a10latitude`, `a10longitude` (mill GPS) | assigning each mill to a hexagon; GPS is never written out |
| `miller_ModC.Sec1.dta` | `a02`, `c05` (type of mill in 2018), `c03` (ownership at the start of the mill's reported history) | counts by type and ownership |
| `miller_ModC.Sec4_6.dta` | `a02`, `year`, `milling_capacity` (fortnightly milling capacity, metric tons) | median capacity per hexagon (2018 values) |

Place them like this, or set `MATS_DATA_DIR` to the folder that contains `miller_data/`:

```
data/mats_2018/miller_data/miller_ModA.dta
data/mats_2018/miller_data/miller_ModC.Sec1.dta
data/mats_2018/miller_data/miller_ModC.Sec4_6.dta
```

## 2. District boundaries

The maps use the 2022 district boundaries published by the Bangladesh Bureau of Statistics
(BBS): `district2022.shp` with its `.shx`, `.dbf`, `.prj` and `.cpg` files. The fields
`DIVISION_N` and `DISTRICT_N` are used for names.

Place it at `data/shapefiles/district2022.shp`, or set `BD_DISTRICT_SHP` to its path.

## 3. Verifying your copy

`checksums.sha256` holds the SHA-256 hashes of the exact files used for the published maps:

```bash
make verify-data
```
