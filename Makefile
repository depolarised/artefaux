.PHONY: setup test lint format corpus figures report download select regenerate smoke clean

PY := .venv/bin/python
PTBXL ?= /data/physionet/ptb-xl-1.0.3
MACECGDB ?= /data/physionet/motion-artifact-contaminated-ecg-database-1.0.0
NSTDB ?= data/sources/nstdb
OUT ?= out/artefaux-v2
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

report:  ## Regenerate the corpus report (Markdown; add PDF=1 to also render a PDF via pandoc)
	$(PY) scripts/reports/generate_corpus_report.py $(if $(PDF),--pdf,)

download:  ## Fetch NSTDB (the only source not in the local PhysioNet mirror)
	$(PY) scripts/download_sources.py --out $(NSTDB)

select:  ## Resolve PTB-XL source ids from your local copy
	$(PY) scripts/select_sources.py --ptbxl $(PTBXL)

regenerate:  ## Build the full corpus from local sources into $(OUT)
	$(PY) scripts/generate.py --ptbxl-dir $(PTBXL) --macecgdb-dir $(MACECGDB) --nstdb-dir $(NSTDB) --out $(OUT) --master-seed $(SEED)

smoke:  ## Build a synthetic corpus (no download) — proves the pipeline end to end
	$(PY) scripts/generate.py --synthetic --out out/smoke --master-seed $(SEED)

clean:  ## Remove generated corpus output (keeps recipes/manifest/figures)
	rm -rf out
