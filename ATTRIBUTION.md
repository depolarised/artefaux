# Attribution and Licensing

**Torsade** is a deterministic ECG stress-test corpus generator that combines openly available source datasets with deterministic corruption models. This document clarifies the licensing terms, attribution requirements, and user obligations.

## Code License

Torsade source code (`src/`, `scripts/`, `recipes/`) is released under the **GNU General Public License v3.0 or later** (GPL-3.0-or-later).

You are free to:
- Use, modify, and distribute the code under the terms of the GPL-3.0-or-later.
- Link to or depend on Torsade in GPL-compatible projects.

You are required to:
- Disclose source code if you distribute binaries.
- Preserve copyright and license notices.
- Document modifications.

See `LICENSE` in the repository root for the full GPL-3.0 text.

## Manifest, Labels, and Documentation License

The corpus definition files (manifest YAML, label YAML, documentation) are released under **Creative Commons Attribution 4.0 International** (CC-BY-4.0).

You are free to:
- Share, adapt, and build upon the corpus definition.
- Use for any purpose (research, education, commercial).

You are required to:
- Provide attribution to Ioannis Valasakis and the Torsade project.
- Link to the license: https://creativecommons.org/licenses/by/4.0/

## Source Data Licenses and Attribution

Torsade does **NOT** redistribute derived signals from source datasets. Users must obtain source data independently from PhysioNet and regenerate the corpus via `make download && make regenerate`.

Each source dataset carries its own license. When using Torsade, you must comply with and cite each source dataset:

### 1. PTB-XL v1.0.3

**License:** Creative Commons Attribution 4.0 International (CC-BY-4.0)

**Citation:**
```
Wagner, P., Strodthoff, N., Bousseljot, R.-D., Samek, W., & Schaeffter, T. (2020).
"PTB-XL, a large publicly available electrocardiography dataset."
Scientific Data, 7, 154.
https://doi.org/10.1038/s41597-020-0495-6
```

**Access:** https://doi.org/10.13026/g4xw-ba04

**How Torsade uses PTB-XL:**
- Source of ~50 clean 12-lead ECG recordings for real-noise pairing.
- Used to provide clinical metadata (age, sex, rhythm class).
- Clinical ground truth provided by PTB-XL+ annotations (Glasgow/Uni-G statements).

**Your obligation:** If you use PTB-XL via Torsade, you must cite the Wagner et al. (2020) paper and provide the PhysioNet DOI.

---

### 2. PTB-XL+ v1.0.1

**License:** Creative Commons Attribution 4.0 International (CC-BY-4.0)

**Citation:**
```
Strodthoff, N., Wagner, P., Wenzel, M., & Samek, W. (2021).
"Deep neural networks for interpretable medical image analysis."
Zenodo. https://doi.org/10.5281/zenodo.4916206
```

**Access:** https://zenodo.org/record/4916206

**How Torsade uses PTB-XL+:**
- Augmented signal-quality annotations (static_noise, burst_noise, baseline_drift, electrodes_problems).
- Glasgow ECG statement labels (e.g., "Left ventricular hypertrophy" from automated interpretation).
- Structured quality flags provide ground truth for naturally poor records.

**Your obligation:** If you use PTB-XL+ annotations via Torsade, cite the Strodthoff et al. source.

---

### 3. MIT-BIH Noise Stress Test Database (NSTDB) v1.0.0

**License:** Open Data Commons Attribution License v1.0 (ODC-BY-1.0) — **attribution required**.  
**Provenance:** Created at the Beth Israel Hospital / MIT (Moody, Muldrow & Mark) and distributed by PhysioNet. Not public domain; you must retain the attribution below.

**Citation:**
```
Moody, G. B., Muldrow, W. G., & Mark, R. G. (1984).
"A noise stress test for arrhythmia detectors."
In Proceedings of the 11th IEEE Engineering in Medicine and Biology Society Conference,
Boston, MA, USA (pp. 381–384).
```

**Access:** https://doi.org/10.13026/c2dv-6e40

**How Torsade uses NSTDB:**
- Primary source of real noise segments (electrode motion, muscle artefact, baseline wander).
- Resampled from native 360 Hz to 500 Hz using scipy.signal.resample_poly.
- Mixed with PTB-XL clean parents at SNR levels {−6, 0, 6, 12, 18} dB to create 30 real-noise stress-test pairs.

**Your obligation:** If you use NSTDB noise via Torsade, cite the Moody et al. (1984) paper and the PhysioNet DOI.

---

### 4. Motion Artifact Contaminated ECG Database (MACECGDB) v1.0.0

**License:** Open Data Commons Attribution License v1.0 (ODC-BY-1.0)  
**Restrictions:** Attribution required; redistribution of derived data must preserve attribution.

**Citation:**
```
Behravan, V., Glover, N. E., Farry, R., Shoaib, M., & Chiang, P. Y. (2015).
Motion Artifact Contaminated ECG Database (version 1.0.0). PhysioNet.
https://doi.org/10.13026/C2JP4G
```

**Access:** https://doi.org/10.13026/C2JP4G

**How Torsade uses MACECGDB:**
- Source of real motion traces (standing / walking / single-jump) for a few "wild" engineering extremes via the `motion_swing` recipe op.
- Unlike NSTDB, the underlying cardiac signal is **not** suppressed, so these motion traces carry residual ECG — a harder, more ECG-like adversarial artefact — and are labelled as a motion source, not clean noise.

**Your obligation:** If you use MACECGDB data via Torsade, comply with the ODC-BY-1.0 license and cite the Behravan et al. (2015) database.

---

### 5. PhysioNet Infrastructure

**Citation:**
```
Goldberger, A. L., Amaral, L. A. N., Glass, L., Hausdorff, J. M., Ivanov, P. C.,
Mark, R. G., Mietus, J. E., Moody, G. B., Peng, C.-K., & Stanley, H. E. (2000).
"PhysioNet: components of a new research resource for complex physiological signals."
Circulation, 101(23), e215–e220.
https://doi.org/10.1161/01.CIR.101.23.e215
```

**Access:** https://physionet.org/

**How Torsade uses PhysioNet:**
- Distribution platform for the source datasets (PTB-XL, PTB-XL+, NSTDB, MACECGDB).
- Provides data integrity (checksums, version control) and persistent DOI assignments.

**Your obligation:** Acknowledge PhysioNet as the repository infrastructure when citing source datasets.

---

## Excluded Datasets

**MIMIC-IV (MIMIC-IV-ECG)** is explicitly **NOT** used in Torsade v1, despite being a high-quality ECG resource, because:

1. **Credentialed access required:** MIMIC-IV requires PhysioNet account registration and agreement to a research data use agreement (RDUA). Not all users have access.
2. **Non-redistributable:** MIMIC-IV records cannot be redistributed, even under anonymous or de-identified form.
3. **Reproducibility constraint:** Including MIMIC-IV would prevent users without credentials from regenerating the full corpus.

If you wish to supplement Torsade with MIMIC-IV-ECG data for your own research, follow the MIMIC-IV RDUA terms directly and cite it separately.

---

## How to Cite Torsade

### Citing the Corpus and Generation Engine

**In-text citation (Author-Year style):**
```
Valasakis (2026) introduced Torsade, a deterministically reproducible stress-test 
corpus for ECG signal-quality validation.
```

**Bibliography entry (BibTeX):**
```bibtex
@software{valasakis2026torsade,
  author       = {Ioannis Valasakis},
  title        = {Torsade: Deterministic {ECG} Noise and Lead-Failure Stress-Test Corpus},
  year         = {2026},
  version      = {1.0.0},
  date         = {2026-07-13},
  url          = {https://github.com/depolarised/torsade},
  license      = {GPL-3.0-or-later},
}
```

For full CFF (Citation File Format) entry, see `CITATION.cff`.

### Citing Source Datasets

When using Torsade, **always cite the source datasets** in addition to Torsade itself:

```bibtex
@article{wagner2020ptbxl,
  author   = {Wagner et al.},
  title    = {PTB-XL, a large publicly available electrocardiography dataset},
  journal  = {Scientific Data},
  year     = {2020},
  volume   = {7},
  pages    = {154},
  doi      = {10.1038/s41597-020-0495-6}
}

@misc{moody1984nstdb,
  author   = {Moody, G. B. and Muldrow, W. G. and Mark, R. G.},
  title    = {{MIT-BIH} Noise Stress Test Database},
  year     = {1984},
  howpublished = {PhysioNet},
  doi      = {10.13026/c2dv-6e40}
}

@inproceedings{silva2011cinc,
  author    = {Silva, I. and Moody, G. B. and Celi, L. A.},
  title     = {Improving the quality of {ECG}s collected using mobile phones and other wireless devices},
  booktitle = {Computing in Cardiology},
  year      = {2011},
  pages     = {273--276}
}
```

---

## Copyright and Authorship

**Torsade v1.0.0** is authored by **Ioannis Valasakis** (wizofe, tungolcild@gmail.com).

**Copyright notice:**
```
© 2026 Ioannis Valasakis. Torsade source code is licensed under GPL-3.0-or-later.
Torsade corpus definition, manifest, labels, and documentation are licensed under CC-BY-4.0.
```

---

## Summary: User Obligations

If you use Torsade, you must:

1. **Cite Torsade** (the corpus and generation engine).
2. **Cite each source dataset** used in your experiments (PTB-XL, PTB-XL+, NSTDB, MACECGDB).
3. **Comply with PhysioNet terms** (responsible, ethical use; retain source attributions). The source datasets used here are openly licensed (CC-BY-4.0 / ODC-BY-1.0) and permit reuse — including commercial — provided attribution is retained.
4. **Comply with each source license:**
   - PTB-XL and PTB-XL+: CC-BY-4.0 (attribution required).
   - NSTDB: ODC-BY-1.0 (attribution required).
   - MACECGDB: ODC-BY-1.0 (attribution required).
5. **Do not claim clinical validity** without independent validation on clinically representative datasets.
6. **Do not redistribute** derived signals from source datasets; users must regenerate via the provided recipes.

---

## Questions?

For licensing questions or requests for alternative licensing arrangements (e.g., scientific licenses for academic collaboration), contact:

**Ioannis Valasakis**  
Email: tungolcild@gmail.com  
GitHub: https://github.com/depolarised
