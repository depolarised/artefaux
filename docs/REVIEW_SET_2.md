<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
-->

# Additional blinded ECG review set

The supplementary definition in `src/artefaux/review.py` creates **85 additional
10-second recordings** and leaves the released 85-record v2 definition and its
review codes untouched. Clean PTB-XL parents are selected from 85 distinct patients
with no patient overlap with the original v2 corpus. Parent selection excludes the
four technical quality flags used by the original workflow.

The new cohort contains:

| Batch | Number | Added artefact |
|---|---:|---|
| Selective extreme | 15 | NSTDB electrode motion, muscle artefact, or baseline wander at −18, −14, or −10 dB SNR, confined to selected leads and exactly one five-second half |
| Lower-noise controls | 10 | None; untouched clean parents |
| Lower-noise mixed | 60 | NSTDB artefact at −2, 0, +6, +12, or +18 dB SNR across single leads, lead subsets, and all leads, for five or ten seconds |

Of the selective extreme cases, eight affect the first half and seven affect the
second half. All leave at least one displayed independent lead untouched. The
60 mixed cases contain 40 full-length and 20 half-length contaminations, including
10 full-length cases affecting all 12 leads. The four all-lead, full-length cases
at −2 or 0 dB carry authored discard hypotheses; human review remains independent.

The user's clarification of "lower noise floor" means **less added noise**.
Artefaux controls noise by SNR, so the second-batch ladder increases SNR relative to
the original −6, −4, −2, 0, +2 dB ladder. Positive SNR means lower noise power for the
same clean lead. Zero and negative anchors preserve difficult whole-record cases.

Corruption is in the acquisition-channel domain: only the chosen stored leads are
modified. There is no electrode-domain propagation through derived leads or the
Wilson central terminal. Both NSTDB channels are used, and each source record,
channel, segment offset, interval, seed, and measured SNR is recorded privately.
Master seed is `20261002`; blind-order seed is `20261003`.

## Generate and share

This is local review tooling requiring the existing `ecg_io` and `signalpaper`
workspace packages, the original blinded PDF/CSV/key, and local PTB-XL/NSTDB data.
For the two small XLS libraries, install the pinned versions into the project venv:

```sh
uv pip install --python .venv/bin/python xlwt==1.3.0 xlrd==2.0.2
MPLCONFIGDIR=/tmp/artefaux-matplotlib .venv/bin/python scripts/generate_review_set.py
```

The script writes genuine Excel 97–2003 **BIFF8 `.xls` files**, with a matching
six-column CSV companion for each reviewer. Each worksheet is plain: one heading
row followed by the data, using default cells with no colours, shading, or theme.
Every newly created XLS is reopened to compare every cell with its source rows.
Existing response cell values and CSV files are preserved. Refreshing an existing
XLS removes presentation styling while retaining every cell value.

To refresh both overflow PDFs and the reviewer ZIPs using the existing second-set
signals, run:

```sh
MPLCONFIGDIR=/tmp/artefaux-matplotlib .venv/bin/python scripts/generate_review_set.py --reuse-corpus
```

To update just the ZIPs after editing a review sheet or its accompanying README,
without plotting or generating signals again:

```sh
.venv/bin/python - <<'PY'
from pathlib import Path
from types import SimpleNamespace
from scripts.generate_review_set import package_reviews

package_reviews(SimpleNamespace(share_dir=Path("reports/review_packs")))
PY
```

`DTC` identifies Derek and `PWM` identifies Peter. The headings are:

```text
Blind ECG code,PWM Leads unsuitable,PWM 50% OK?,PWM comments,PWM decision,Agreed handling
Blind ECG code,DTC Leads unsuitable,DTC 50% OK?,DTC comments,DTC decision,Agreed handling
```

| Reviewer handoff | Contents |
|---|---|
| `reports/review_packs/artefaux85DTC_set1_review.zip` | First-set blinded overflow PDF and Derek's first-set XLS/CSV |
| `reports/review_packs/artefaux85PWM_set2_review.zip` | Second-set blinded overflow PDF, Peter's second-set XLS/CSV, and blinded WFDB/GRIASCII records |
| `reports/review_packs/artefaux85DTC_set2_review.zip` | Second-set blinded overflow PDF, Derek's second-set XLS/CSV, and blinded WFDB/GRIASCII records |

Standalone workbooks are under `reports/review_packs/set1/` and `set2/`. The first
set also has `artefaux85PWM.xls`, containing the six example rows supplied by the
user, without changing the original joint comments CSV. Those entries are kept in
Peter's sheet only. All review cells in the new second-set workbooks start blank.

The PDF uses the original full-disclosure layout: eight independent leads
(`I`, `II`, `V1`–`V6`), each displayed for the full ten seconds, at 25 mm/s and
10 mm/mV. The second-set PDF shows **raw signals** with an explicit footer. This
preserves the visible five-second boundary; the old diagnostic zero-phase filter
can spread a localized baseline excursion into the otherwise clean half. Both sets
use the original report's **overflow mode**: traces can extend beyond their
allocated lead bands, with no per-band clamping or clipping banners. The first set
retains its original diagnostic filtering and the exact page-to-code mapping from
the original private key. The exported signals retain their amplitude.

The PDFs are named `artefaux85_set1_blind_overflow.pdf` and
`artefaux85_set2_blind_overflow.pdf` within their respective handoff directories.
The previously shared `*_blind.pdf` filenames are refreshed with the same overflow
PDFs; reviewer ZIPs contain the explicitly named overflow versions.

Each second-set row code matches its PDF page and its `REV-NNN` signal filenames.
WFDB exports retain all 12 leads, 5000 samples per lead, 500 Hz, and millivolt units.
GRIASCII exports use the existing v1.5 conversion workflow with 1000 ADC counts/mV
and a verified round trip. Blinded signal headers contain only neutral codes and
technical acquisition metadata. Both sets start at `REV-001`, so their set numbers
must accompany shared files.

## Private verification

`out/artefaux-review-set2/` contains clean parents, labels, recipes, source-selection
audit, source SHA-256 hashes, generation audit, GRIASCII verification, and
`PRIVATE_blind_key.csv`. These are coordinator artifacts and are excluded from
reviewer ZIPs. The source datasets are attributed in the repository's
`ATTRIBUTION.md`; generated signals and review handoffs remain gitignored.

The generation checks the written WFDB signals, not just arrays in memory: every
sample outside the target lead/time mask must equal its saved clean parent exactly.
Requested and measured SNR must agree within 0.5 dB on each contaminated lead.
Original CSV, PDF, and private key hashes are checked again after packaging to
confirm they remain unchanged. The tests also verify half-strip recovery, actual
noise-power reduction across the SNR ladder, and quote-preserving XLS conversion.

The completed handoff was verified on 2026-10-02: 85 pages per set, unchanged blind
codes and review cell values, plain XLS formatting, intact reviewer ZIPs containing
the current overflow PDFs, and no private truth in those ZIPs. The largest measured
post-storage SNR error was 0.0533 dB (rounded up); all untargeted samples matched
their saved clean parents exactly. The full suite passed 79 tests, and the five
review tests passed again after the presentation changes. Test counts describe
that verification run and are not a permanent corpus invariant.
