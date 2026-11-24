# Rebuild the maps from the MATS 2018 miller data.
#
#   make               regenerate docs/index.html and figures/*.png
#   make preview       serve the interactive map at http://localhost:8000
#   make verify-data   check the input files against data/checksums.sha256
#   make check         pre-publication privacy checks (run before every push)
#
# Data are read from data/ by default; override with MATS_DATA_DIR and
# BD_DISTRICT_SHP (see data/README.md).

PY ?= uv run --frozen python
export MPLBACKEND = Agg

.PHONY: all map preview verify-data check clean

all: map

map:
	cd analysis && $(PY) -m nbconvert --to notebook --execute mats_miller_map.ipynb \
	    --output-dir ../build --ExecutePreprocessor.timeout=600

preview:
	$(PY) -m http.server --directory docs 8000

verify-data:
	$(PY) scripts/verify_data.py

check:
	python3 scripts/check_repo.py

clean:
	rm -rf build
