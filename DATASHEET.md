# Datasheet for Torsade: ECG Noise and Lead-Failure Stress-Test Corpus

**Version:** 1.0.0  
**Release date:** 2026-07-13  
**Maintainer:** Ioannis Valasakis (wizofe)  
**Repository:** https://github.com/wizofe/torsade  
**License:** Code (GPL-3.0-or-later); manifest, labels, documentation (CC-BY-4.0)

## 1. Motivation

### Why does the corpus exist?

Torsade addresses a gap in ECG signal-quality evaluation: there is no widely available, richly labelled, deterministically reproducible corpus specifically designed to stress-test noise detectors and lead-failure handlers. Existing datasets emphasize clinical diversity (arrhythmia prevalence, demographics) rather than systematic coverage of artefact and corruption modes.

This corpus is designed for:

- **Validating signal-quality gates** (e.g., `signalguard`): does the gate correctly reject or downgrade records with poor signal integrity?
- **Benchmarking noise detectors** (e.g., `noiseguard`): does the detector identify contaminated leads at various SNR levels and across different noise types?
- **Testing lead-off and electrode-domain handling**: how do systems behave when leads are flatlined, clipped, inverted, or disconnected?
- **Exercising extreme-condition code paths**: saturation, NaN, rail-saturation, and digital discontinuities that may appear under equipment failure or data corruption.

### Primary use case

Torsade is a **stress-test corpus**, not a clinically representative epidemiological dataset. It is intended for robustness validation of algorithms and systems, **not** for training, external validation against clinical prevalence, or population health inference.

### Intended audience

- Developers and researchers building ECG signal-processing and interpretation pipelines.
- QMS teams validating medical device signal-quality thresholds.
- Researchers studying ECG artefact and noise rejection under adversarial or failure conditions.

## 2. Composition

### Dataset structure

Torsade v1 contains **~67 test records** (derived from publicly available sources) plus **~50–55 paired clean parent records** (from open-access PhysioNet datasets). The corpus is organized by corruption mode, not by clinical condition.

| Category | Count | Source | Corruption Type | Clean Parent |
|----------|-------|--------|-----------------|--------------|
| Naturally poor | 15 | CinC Challenge 2011 (10) + PTB-XL quality flags (5) | Inherent signal degradation | No |
| Real-noise SNR ladder | 30 | PTB-XL 500 Hz base + NSTDB noise | EM, MA, BW at {−6, 0, 6, 12, 18} dB SNR | Yes (PTB-XL) |
| Engineering extremes: single-lead | 11 | Synthetic corruption | Clipping, flatline, lead-off, NaN, swings, step-recovery, polarity inversion, intermittent lead-off | Varies |
| Engineering extremes: multi-lead | 11 | Electrode-domain models | Limb/chest electrode corruption (RA/LA/LL) | Varies |

**Total records: ~67**  
**Paired clean parents: ~50–55**

### Data format

- **Signal representation:** (12, T) float64 arrays in **millivolts**, lead order [I, II, III, aVR, aVL, aVF, V1, V2, V3, V4, V5, V6].
- **Sampling rate:** 500 Hz (deterministic resampling from source; NSTDB resampled from 360 Hz native).
- **Duration:** typically 10 seconds per record (exact duration depends on source; resampling preserves record length).
- **Signal encoding:** WFDB format (`.dat` + `.hea` header) for portability; generation produces deterministic bit-for-bit output.

### Data types and quantity

- **12-lead ECG waveforms:** 12 × 5000 samples = 60,000 samples per 10-second record.
- **Labels:** structured YAML (clinical parent metadata, corruption truth, expected behaviour).
- **Manifest:** indexed YAML with record-level pointers and provenance hashes.

### Sources (NOT redistributed; users must obtain independently)

1. **PTB-XL v1.0.3** (Wagner et al., *Scientific Data* 2020)
   - Publicly available; CC-BY-4.0 license.
   - 21,837 12-lead ECG recordings at 500 Hz, ages 16–89 years, mixed rhythms and pathologies.
   - Retrieved from PhysioNet: https://doi.org/10.13026/g4xw-ba04
   - Torsade uses ~50 records as clean parents for real-noise mixing.

2. **PTB-XL+ v1.0.1** (Strodthoff et al., *arXiv* 2021)
   - CC-BY-4.0 license; augmented annotations of PTB-XL.
   - Provides Glasgow/Uni-G ECG statements and signal-quality flags (static_noise, burst_noise, baseline_drift, electrodes_problems).
   - Retrieved from Zenodo: https://doi.org/10.5281/zenodo.4916206
   - Used to annotate parent records with clinical ground truth and pre-existing quality markers.

3. **MIT-BIH Noise Stress Test Database (NSTDB) v1.0.0** (Moody, Muldrow, Mark 1984)
   - Open Data Commons Attribution License v1.0 (ODC-BY-1.0); attribution required.
   - Three real-noise records — electrode motion (em), muscle artefact (ma), and baseline wander (bw) — at 360 Hz, recorded from active subjects with electrodes positioned to suppress the underlying ECG.
   - Retrieved from PhysioNet: https://doi.org/10.13026/c2dv-6e40
   - Torsade uses these as primary noise sources for SNR ladder and real-noise pairs; resamples to 500 Hz.

4. **PhysioNet/CinC Challenge 2011 v1.0.0** (Silva, Moody, Celi 2011)
   - Open access (PhysioNet Data Use Agreement); no commercial restriction.
   - 649 12-lead ECG recordings selected for poor signal quality (unacceptable for clinical interpretation).
   - Retrieved from PhysioNet: https://doi.org/10.13026/tnya-rb03
   - Torsade uses 10 of these as naturally poor records (no clean parent).

5. **PhysioNet** (Goldberger et al., *Circulation* 2000)
   - Repository and associated infrastructure.
   - https://physionet.org/ and https://doi.org/10.1161/01.CIR.101.23.e215

### Exclusions and scope limitations

- **No MIMIC-IV:** Credentialed access only; not redistributable.
- **No clinical metadata beyond published annotations:** Age, sex, and rhythm class are sourced from published datasets; no additional patient identifiers or clinical notes.
- **No synthetic electrocardiograms:** The corpus uses real recordings + real noise + deterministic artefact models, not generated synthetic waveforms (with minor exceptions in engineering extremes for extreme amplitude swings and step-recovery functions).

## 3. Collection Process

### Data acquisition

**Naturally poor records:** Retrieved directly from CinC Challenge 2011 (previously curated as high-artefact set) and PTB-XL with pre-computed quality flags indicating known degradation.

**Real-noise pairs:** PTB-XL records selected at random (stratified by rhythm class) and paired with NSTDB noise segments, resampled to 500 Hz and mixed according to the SNR ladder (−6, 0, 6, 12, 18 dB).

**Engineering extremes:** Single-lead corruptions generated via deterministic parametrised models (clipping, flatline, digital missing); multi-lead corruptions generated by electrode-domain inference (recover limb-electrode potentials, corrupt electrode domain, rederive 12 leads).

### Sampling strategy

- **Naturally poor:** exhaustive (all suitable records from source datasets).
- **Real-noise pairs:** stratified by PTB-XL rhythm class; one SNR variant per parent.
- **Engineering extremes:** systematic exploration of corruption modes (one per record, or paired multi-lead).

### Determinism and reproducibility

- **Single master seed:** all records generated from a deterministic numpy `SeedSequence`.
- **Per-record RNG:** derived via `SeedSequence(entropy=master_seed, spawn_key=(record_index,))`.
- **Bit-for-bit reproducibility:** `make download && make regenerate` produces identical output on any platform (given identical source file versions and SHA-256 hashes).

### Provenance tracking

- **Source file hashing:** SHA-256 of every downloaded source file; manifest records digest and version.
- **Record-index mapping:** each Torsade record linked to source dataset and source record ID.
- **Versioning:** source dataset versions (PTB-XL v1.0.3, NSTDB v1.0.0, etc.) pinned in manifest.

## 4. Preprocessing, Cleaning, and Labeling

### Preprocessing steps

1. **Resampling:** All signals resampled to 500 Hz using `scipy.signal.resample_poly` (Polyphase filtering; deterministic).
2. **Gain normalization:** Signals remain in original recording units (mV) from source datasets; no scaling or unit conversion.
3. **DC removal:** Median removal (over each lead) applied before SNR computation; not applied to final signal (signals preserve original DC offset).

### Quality assurance

- **Non-finite checks:** all signals validated to contain only finite values before writing WFDB output (raises `ECGReadError` on NaN or Inf).
- **Lead order validation:** 12-lead order [I, II, II, aVR, aVL, aVF, V1, V2, V3, V4, V5, V6] verified against each source.
- **Amplitude checks:** peak-to-peak amplitudes recorded for clipping detection and validation.

### Labeling scheme

Each record receives **three layers of labels**:

1. **Clinical parent:** source dataset, source record ID, age, sex, rhythm class, Glasgow ECG statements (from PTB-XL+), pre-existing quality flags, has_clean_parent indicator.

2. **Corruption truth:** complete ordered sequence of applied corruptions, each with:
   - Operation type (e.g., `add_noise`, `clip_lead`, `disconnect_electrode`).
   - Leads and electrodes affected.
   - Noise type and source (NSTDB record, segment, start sample).
   - SNR parameters (requested, measured post-quantization; SNR computed over contaminated interval only).
   - Mixing coefficient (α from power-based formula).
   - Amplitude metrics (peak-to-peak before/after per lead, clipping fraction, intervals).

3. **Expected behaviour:** authored from the recipe (NOT adjudicated by clinicians):
   - Record-level quality ∈ {diagnostic, limited, rhythm_only, reject} (signalguard vocabulary).
   - Per-lead quality ∈ {good, borderline, bad} (signalguard vocabulary).
   - Rejected leads and derived-leads-invalidated flags.
   - Data-integrity failure type (if applicable: clipping, flatline, constant-ADC, lead-off, NaN, polarity-inversion).
   - Discard flags for specific detectors (`noiseguard_discard_record`, `noiseguard_bad_leads`).

### Labeling methodology

- **Corruption-truth labels** are **deterministic** — generated directly from the applied recipe; no post-hoc adjudication.
- **Expected-behaviour labels** are **prescriptive** — authored to reflect design intent for how a well-tuned gate or detector **should** respond.
- **Clinically-derived labels** (rhythm, Glasgow statements, quality flags) are **sourced** from published datasets (PTB-XL, PTB-XL+, CinC Challenge).

See `docs/LABEL_SCHEMA.md` for the complete schema and JSON examples.

## 5. Uses

### Recommended uses

- Algorithmic validation: benchmarking signal-quality gates (`signalguard`) and noise detectors (`noiseguard`) against known ground truth.
- Robustness testing: exercising code paths for edge cases (lead-off, clipping, NaN, polarity inversion).
- Stress-test scenario planning: designing acceptance criteria for systems that must operate under degraded signal conditions.
- Reproducible research: publishing algorithm validation results with reference to a versioned, deterministically reproducible corpus.

### Cautioned uses (possible but not primary)

- **Clinical prevalence estimation:** The corpus is **stress-test biased**, not epidemiologically balanced. Do not use to estimate prevalence of any noise type or lead-failure mode in real populations.
- **Training noise-robust models:** Real NSTDB noise is used, but SNR ranges and contamination patterns are artificial. Models trained on Torsade may not generalize to naturalistic field recordings. Consider supplementing with in-the-wild datasets.
- **Tuning clinical thresholds without external validation:** Expected-behaviour labels are authored from recipes, not adjudicated by clinicians. Always validate tuned thresholds against independent clinical datasets before deployment.

### Prohibited uses

- Diagnostic inference: Never apply ECG interpretation algorithms trained on or validated against Torsade to real patient data without independent clinical validation on datasets representative of the intended use population.
- Redistribution of derived signals: The corpus does NOT redistribute NSTDB, PTB-XL, or CinC Challenge records; users must obtain these independently and regenerate via the provided recipes.

## 6. Distribution

### Availability

- **Code:** https://github.com/wizofe/torsade (GPL-3.0-or-later).
- **Corpus definition (recipes, manifest, labels):** Distributed with the repository (CC-BY-4.0).
- **Derived signals:** Users must fetch source datasets from PhysioNet and regenerate via `make download && make regenerate`.

### Licensing

- **Code:** GPL-3.0-or-later.
- **Manifest, labels, and documentation:** CC-BY-4.0 (Attribution 4.0 International).
- **Source data:** Each source carries its own license (PTB-XL: CC-BY-4.0; NSTDB: ODC-BY-1.0; CinC Challenge 2011: PhysioNet open access; PTB-XL+: CC-BY-4.0). Users must comply with each source's terms.

### Access and reproducibility

Torsade requires **no credentialed access.** All source datasets are openly available (with the exception of MIMIC, which is explicitly excluded). A user with internet access and sufficient disk space can:

```bash
git clone https://github.com/wizofe/torsade.git
cd torsade
make download     # Fetches PhysioNet source files
make regenerate   # Builds corpus deterministically
```

## 7. Maintenance

### Version control

Torsade uses semantic versioning (MAJOR.MINOR.PATCH).

- **v1.0.0 (2026-07-13):** Initial release. Deterministic generation engine, full corpus definition (recipes + manifest + labels), all three corruption categories.

### Dataset versioning

Each major version pins source dataset versions in the manifest:
- PTB-XL v1.0.3
- PTB-XL+ v1.0.1
- NSTDB v1.0.0
- CinC Challenge 2011 v1.0.0

If source datasets are updated, a new Torsade version is required to maintain reproducibility.

### Maintenance plan

- **Bug fixes:** Corrected corruption recipes or label errors warrant a patch release (v1.0.1, v1.0.2, etc.).
- **New corruption categories:** New categories of engineering extremes warrant a minor version bump (v1.1.0).
- **Corpus expansion:** Additional records or lead configurations warrant a minor bump.
- **Breaking changes:** Changes to the YAML schema, lead order, or sampling rate require a major version bump.

### Contact and reporting issues

- **GitHub Issues:** https://github.com/wizofe/torsade/issues
- **Maintainer:** Ioannis Valasakis (wizofe), tungolcild@gmail.com

## 8. Limitations and Caveats

### By design

1. **Stress-test bias:** The corpus oversamples extreme corruption modes relative to clinical prevalence. Results validating an algorithm on Torsade do **not** imply clinical robustness; always validate on independent epidemiologically balanced datasets.

2. **Synthetic electrode model:** Multi-lead electrode-domain corruptions use the classical Wilson Central Terminal definition (WCT = (RA + LA + LL)/3). This is an **idealised model**—the true WCT is non-zero and varies throughout the cardiac cycle. Torsade does not model individual chest-wall geometry, electrode contact impedance, or torso forward models. Use engineering extremes as *unit tests*, not as surrogates for real inter-lead dependencies.

3. **No torso-forward model:** Lead-off and electrode-disconnection corruptions are modelled as zeroing the electrode potential in the RA-reference frame, then recomputing 12 leads. This does not model mutual capacitance between electrodes or skin-impedance effects.

4. **Real NSTDB noise + synthetic engineering extremes:** SNR ladder records use **real recorded noise** (NSTDB EM, MA, BW); clipping and flatline are synthetic parametric models. The corpus is **not** uniformly synthetic; it blends real artefact with engineered edge cases.

5. **Deterministic NaN encoding caveat:** NaN values (from digital-missing errors) cannot be stored in WFDB's binary format and are not representable in an `ECGRecord` (which enforces finite values). Engineering-extreme records with NaN corruptions will be **zero-filled on read** by standard WFDB readers. The expected-behaviour label documents this; validation should test the *reader's* graceful degradation, not the on-disk value.

### Known limitations in v1

- **No inter-electrode physiological constraints:** Torsade does not model the 12-lead space as a low-dimensional manifold or enforce Dower matrix constraints. Extreme multi-lead corruptions may violate real cardiac electrophysiology.
- **No non-stationary noise:** All NSTDB segments are treated as stationary. Real electrode motion and muscle artefact evolve over time; Torsade does not model time-varying noise transfer functions.
- **Limited rhythm diversity in real-noise pairs:** PTB-XL parents are stratified by rhythm but not equally sampled; sinus-rhythm records are overrepresented.

## 9. Key References

### Gebru et al. framework

This datasheet follows Gebru et al. (2021):  
Gebru, T., Morgenstern, J., Vecchione, B., et al. (2021). "Datasheets for Datasets." *Communications of the ACM*, 64(12), 86–92. https://doi.org/10.1145/3458723

### Source datasets

- Wagner, P., Strodthoff, N., Bousseljot, R.-D., et al. (2020). "PTB-XL, a large publicly available electrocardiography dataset." *Scientific Data*, 7, 154. https://doi.org/10.1038/s41597-020-0495-6
- Strodthoff, N., Wagner, P., Wenzel, M., & Samek, W. (2021). "Explaining deep neural networks and beyond: a review of methods and applications." *arXiv* preprint arXiv:2105.02766.
- Moody, G. B., Muldrow, W. G., & Mark, R. G. (1984). "A noise stress test for arrhythmia detectors." In *Proceedings of the 11th IEEE Engineering in Medicine and Biology Society Conference* (pp. 381–384).
- Silva, I., Moody, G. B., & Celi, L. A. (2011). "Improving the quality of ECGs collected using mobile phones and other wireless devices." *Proceedings of the 2011 Computing in Cardiology* (pp. 273–276).
- Goldberger, A. L., Amaral, L. A. N., Glass, L., et al. (2000). "PhysioNet: components of a new research resource for complex physiological signals." *Circulation*, 101(23), e215–e220. https://doi.org/10.1161/01.CIR.101.23.e215

---

**Citation:** When using Torsade, please cite both the corpus and its source datasets. See `CITATION.cff` for BibTeX and other formats.
