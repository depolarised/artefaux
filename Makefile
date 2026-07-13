.PHONY: setup test lint format corpus figures download select regenerate smoke clean

PY := .venv/bin/python
SOURCES ?= data/sources
OUT ?= out/torsade-v1
SEED ?= 20260713

setup:  ## Create the uv environment and install (with dev + figures extras)
	uv venv .venv
	uv pip install -e ".[dev,figures]"

test:  ## Run the test suite
	$(PY) -m pytest

lint:  ## Lint and format-check
	.venv/bin/ruff check src tests scripts
	.venv/bin/black --check src tests scripts

format:  ## Auto-format and fix
	.venv/bin/ruff check --fix src tests scripts
	.venv/bin/black src tests scripts

corpus:  ## Regenerate the shipped corpus definition (recipes/corpus.yaml + manifest)
	$(PY) scripts/export_corpus.py

figures:  ## Regenerate the documentation figures
	$(PY) scripts/make_figures.py --out figures

download:  ## Fetch the small open sources (NSTDB, CinC Challenge 2011)
	$(PY) scripts/download_sources.py --out $(SOURCES)

select:  ## Resolve PTB-XL source ids from your local copy (needs $(SOURCES)/ptbxl)
	$(PY) scripts/select_sources.py --ptbxl $(SOURCES)/ptbxl --challenge2011 $(SOURCES)/challenge2011

regenerate:  ## Build the full corpus from local sources into $(OUT)
	$(PY) scripts/generate.py --sources $(SOURCES) --out $(OUT) --master-seed $(SEED)

smoke:  ## Build a synthetic corpus (no download) — proves the pipeline end to end
	$(PY) scripts/generate.py --synthetic --out out/smoke --master-seed $(SEED)

clean:  ## Remove generated corpus output (keeps recipes/manifest/figures)
	rm -rf out
