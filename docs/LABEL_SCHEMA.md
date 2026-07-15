# Label schema

Every Artefaux record ships a JSON label with three layers. The **corruption truth**
records exactly what was done; the **expected behaviour** records what a correct
quality gate should do — authored deterministically from the recipe, not by running
any detector.

## Layer 1 — clinical parent

What the underlying ECG *is*, inherited from the untouched parent.

| Field | Meaning |
|---|---|
| `source_dataset` | `ptbxl` (parents) \| `nstdb` \| `macecgdb` (noise sources) |
| `source_record_id` | Resolved source record id (or `null` before selection) |
| `age_years`, `sex` | De-identified demographics (id/name never stored) |
| `rhythm_class` | **Authored/representative** intended rhythm (`sinus`, `afib`, `pac_pvc`, `bbb_conduction`, `st_t`, `flutter_svt`) — *not* read from the source record |
| `glasgow_statements` | Reserved for the PTB-XL+ Uni-G statement layer — **empty in v1** (not yet wired) |
| `ptbxl_quality_flags` | Native PTB-XL flags for naturally-poor records |
| `has_clean_parent` | Whether an untouched paired parent is shipped |

## Layer 2 — corruption truth

Exactly what was done, step by ordered step.

| Field | Meaning |
|---|---|
| `seed` | The record's deterministic seed |
| `steps[]` | Ordered corruption steps |
| `leads_with_any_corruption` | Union of affected leads |

Each step: `op`, `leads_affected`, `electrodes_affected`, `noise_type`,
`noise_source_record`, `noise_source_start_sample`, `interval_s`,
`snr_requested_db`, `snr_measured_db`, `alpha`, `amplitude` (per-lead p2p
before/after + clip fraction/intervals), and `params`.

## Layer 3 — expected behaviour

How a well-behaved gate should respond, in the internal tools' vocabularies. These
are **authored from the recipe**; Artefaux never runs the detectors to produce them.

| Field | Vocabulary |
|---|---|
| `record_quality` | `signalguard` `RecordQuality`: `diagnostic` \| `limited` \| `rhythm_only` \| `reject` |
| `lead_quality` | per-lead `signalguard` `QualityLabel`: `good` \| `borderline` \| `bad` |
| `rejected_leads`, `derived_leads_invalidated` | leads a gate should drop / invalidate |
| `reason_codes` | expected `signalguard` reason codes (e.g. `LEAD_I_BAD`, `LEAD_REVERSAL_SUSPECTED`) |
| `noiseguard_discard_record` | expected `noiseguard` binary record discard |
| `noiseguard_bad_leads` | expected `noiseguard` per-lead flags |
| `data_integrity_failure` | true for NaN / flat / constant / rail cases |
| `integrity_failure_type` | e.g. `digital_missing_channel`, `flatline_zero`, `rail_saturation` |

The two consumers differ deliberately: `noiseguard` is a binary per-lead + record
discard model; `signalguard` is a graded gate. A record can be `limited` for
`signalguard` yet `discard=false` for `noiseguard`, and the label captures both.

## Example (abridged)

```json
{
  "record_id": "nlf_eng_005_overload_v3",
  "group": "engineering",
  "fs": 500,
  "n_samples": 5000,
  "clinical_parent": {
    "source_dataset": "ptbxl", "source_record_id": "00987_hr",
    "rhythm_class": "sinus", "has_clean_parent": true
  },
  "corruption_truth": {
    "seed": 812734,
    "steps": [
      {
        "op": "overload_swing", "leads_affected": ["V3"],
        "interval_s": [0.0, 10.0],
        "amplitude": [{"lead": "V3", "p2p_before_mv": 1.9, "p2p_after_mv": 10.0,
                       "clipped": true, "clip_fraction": 0.21}],
        "params": {"requested_p2p_mv": 30.0, "rail_mv": 5.0}
      }
    ],
    "leads_with_any_corruption": ["V3"]
  },
  "expected_behaviour": {
    "record_quality": "limited",
    "lead_quality": {"I": "good", "II": "good", "V3": "bad", "...": "good"},
    "noiseguard_discard_record": false,
    "noiseguard_bad_leads": [],
    "data_integrity_failure": true,
    "integrity_failure_type": "rail_saturation"
  }
}
```

The authoritative per-record specs live in `recipes/corpus.yaml`; the `manifest.csv`
gives a one-row-per-record index of these fields.
