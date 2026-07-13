# Generation algorithm

This document specifies exactly how each corruption is produced. All of it is
deterministic given the master seed.

## 0. Canonical representation

Every parent is loaded into a `(12, T)` `float64` mV array, canonical lead order,
resampled to **500 Hz** with `scipy.signal.resample_poly` (a rational, deterministic
polyphase resampler). NSTDB noise is resampled from its native **360 Hz** the same
way. Limb leads absent from a source header are derived from I and II.

## 1. Real-noise SNR mixing (`mixing.mix_lead`)

For a clean lead `x`, a real noise segment `n`, and a requested SNR `s` (dB):

```
α = sqrt( Px / (Pn · 10^(s/10)) )
y = x + α · n
```

`Px` and `Pn` are the mean-square powers **after removing the median (DC)**, computed
**over the contaminated interval only** — so a short burst is scaled against the
signal it actually overlaps, not the whole 10 s window. Both the requested SNR and
the *measured* post-quantization SNR are recorded in the label.

The same physical noise trace is scaled per-lead to the target SNR when a step
contaminates several leads, mirroring a single acquisition seeing one disturbance.

**Noise sources.** The 30 SNR-ladder pairs use **NSTDB** `em`/`ma`/`bw`, whose
records suppress the underlying ECG so the added signal is near-pure artefact. A few
"wild" engineering cases instead use **MACECGDB** — real standing/walking/jumping
motion (`motion_swing` op). MACECGDB is *ambulatory ECG* and does not suppress the
cardiac signal, so it carries residual ECG; that makes it a harder, more ECG-like
adversarial artefact, and it is labelled as a motion source, not as clean noise.

## 2. Electrode-domain corruption (`electrode_domain`)

A loose electrode corrupts a *set* of leads. Torsade models this exactly:

1. Recover limb-electrode potentials in the RA-as-reference gauge:
   `RA ≡ 0`, `LA = lead I`, `LL = lead II`.
2. Reconstruct chest-electrode potentials `Ck = Vk + WCT`, where
   `WCT = (RA + LA + LL) / 3`.
3. Add an artefact potential to the chosen electrode(s) (RA/LA/LL or C1..C6).
4. Recompute `WCT` and rederive all twelve leads:
   ```
   I  = LA − RA       II  = LL − RA      III = LL − LA
   aVR = RA − (LA+LL)/2   aVL = LA − (RA+LL)/2   aVF = LL − (RA+LA)/2
   Vk = Ck − WCT
   ```

Because leads are electrode *differences*, the RA-reference gauge is valid (a common
offset on all electrodes cancels). A limb-electrode artefact therefore shifts the
chest leads via the recomputed WCT, and invalidates the affected derived limb leads —
which the label records.

> **Assumption.** The classical `WCT = (RA+LA+LL)/3` is an approximation; the true
> central-terminal potential varies through the cardiac cycle and with electrode
> placement. Torsade uses the classical definition. Read this as an idealised
> electrode model, **not** a torso forward model.

## 3. Precordial coupling (`precordial`)

Adjacent chest leads share a common motion component. Each target lead's noise is
`w·n_shared + (1−w)·n_independent` (unit-power components), e.g.
`n_V4 = 0.8·n_shared + 0.2·n_1`, so leads are correlated but distinct, then mixed at
the target SNR.

## 4. Engineering extremes (`engineering`)

| Builder | Effect | Integrity failure? |
|---|---|---|
| `build_swing` | Large electrode-motion swing to a target p2p; optional rail clip (overload) | only if clipped |
| `build_flatline` | Zero-fill (dead channel) | yes (`flatline_zero`) |
| `build_constant_adc` | Stuck non-zero constant | yes (`constant_adc`) |
| `build_lead_off` | Near-zero content with weak drift | yes (`lead_off`) |
| `build_digital_missing` | Set channel to NaN | yes (`digital_missing_channel`) |
| `build_step_recovery` | Step baseline that decays exponentially | no |
| `build_opposite_polarity` | Invert a lead (reversed electrode) | no (lead-reversal) |
| `build_intermittent_lead_off` | Dropouts with reconnection transients | yes (`intermittent_lead_off`) |

All amplitude changes are tracked (peak-to-peak before/after, clip fraction and
intervals). For overload cases both the requested pre-clip amplitude and the actual
post-clip amplitude are stored, so the SNR label stays honest once the rail is hit.

**Data-integrity vs noise.** NaN / flat / constant / rail cases are labelled
`data_integrity_failure` with an `integrity_failure_type`, **not** as noise. Note
that `ECGRecord` forbids non-finite samples and that some WFDB readers zero-fill NaN
on read — so the *expected behaviour* for these cases is about the reader's handling.

## 5. Obtaining the sources

PTB-XL (500 Hz hi-res), PTB-XL+, and MACECGDB are read from a local PhysioNet mirror
(default `/data/physionet/{ptb-xl-1.0.3, ptb-xl-plus-1.0.1,
motion-artifact-contaminated-ecg-database-1.0.0}`; override with the `PTBXL` /
`MACECGDB` Make variables). The **only** source not typically mirrored is NSTDB, so
that is the one thing `make download` fetches:

```bash
make download        # NSTDB only (small; via wfdb.dl_database)
make select          # resolve PTB-XL parent ids from your local copy (seeded)
make regenerate      # builds records/, labels/, manifest, provenance into ./out
```

To smoke-test the whole pipeline with **no** download:

```bash
python scripts/generate.py --synthetic --out out/smoke
```
