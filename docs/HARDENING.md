# Research hardening and operating instructions

This release repairs reproducible software boundary defects. It does not establish clinical commissioning, generalized model qualification or a durable multi-user service. `/health` exposes these limits through `readiness`; `production_ready` and `clinical_release` remain false. The implemented access model is one trusted operator. `OPENRAD_DEPLOYMENT_PROFILE` defaults to `research`; unsupported shared/clinical profiles are refused at server startup.

## Install and start

Use a dedicated environment with Python 3.11 or newer. CI tests 3.11 and 3.13; retain the exact resolved environment and revision for any scientific comparison. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install '.[app,api,test]'
python -m pip check
python -m pytest validation/tests -q
export OPENRAD_DATA_ROOTS='["/authorized/raw-case-or-parent", "/authorized/public-cache"]'
export STORAGE_DIR="$PWD/storage/sessions"
python -m streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501
```

Replace input placeholders with existing authorized directories. Originals must remain read-only; use OS/container read-only mounts for enforcement. Application checks do not constrain arbitrary trusted Python. Keep derivatives outside input roots and never change source values, geometry or contour labels to obtain a pass. Credentials belong in process memory or secret storage, never source, logs or Git.

For the REST service, set `PORT` (default 8080), configure `CORS_ORIGINS` for the intended frontend, then run `python server.py`. It binds all interfaces for Cloud Run compatibility. Platform authentication, approved input mounts and network access must be enforced by the operator before remote exposure. CORS does not authorize callers. The current implementation does not provide per-tenant ownership or durable cross-instance storage. The container serves the API, not Streamlit, and does not contain local patient files.

The REST `/api/v1/agent/run` endpoint is deterministic. It rejects hosted `model` selection rather than silently ignoring it. Dynamic Gemini use is a separate local workflow; offline intake is not a live model call. Test hosted availability and provider privacy with nonpatient controls before authorized use. Private model reasoning is not a clinical decision or audit record.

Packaged policy resources are read through `src.config.load_skill_policies()` independently of the current directory. Root skill files remain canonical; a test enforces identical packaged copies.

## Input and execution limits

Direct dose tools preflight supported DICOM/NPY shapes before decoding/conversion. NPY inputs are read-only mapped, must have numeric non-object dtypes and supported 1.0/2.0 headers; no object deserialization or string-to-float conversion is allowed. Unsupported formats return generic errors without file contents. Non-DICOM dose still requires explicit per-axis spacing in mm and assumes Gy with zero origin.

Default dose limit: **2,000,000 voxels**. `OPENRAD_MAX_DOSE_VOXELS` can select 1–10,000,000; increasing it requires a measured memory/time qualification. Source-file cap is 128 MiB; text-dose parsing additionally caps files at 8 MiB. The model-evaluation contract retains its stricter per-request limit of at most 1,000,000 voxels. No sampling, downscaling or silent resolution reduction is used to pass a budget.

REST calculations use one active job per process by default. `OPENRAD_MAX_CONCURRENT_JOBS` accepts 1–8. At capacity the API returns HTTP 429; retry after the active operation completes. This is admission control, not a distributed job queue, hard execution timeout or cancellation guarantee. Before shared use, qualify isolated workers, concurrency, peak memory, timeouts and recovery using the actual workloads and container memory. A health check is not a capacity test.

## Numerical contracts and reports

- Physical absorbed dose is strictly nonnegative; the guard only accepts zero tolerance. Never clip or relax a negative input to manufacture a pass.
- Energy requires finite real numeric values, excluding booleans, throughout shared tools. Supported application range is 0.01–250 MeV; this is not a universal limit on all physical beams.
- Complete cumulative DVHs must have paired finite 1D arrays, increasing nonnegative dose bins, bounded non-increasing volume, 0 Gy/100% start and zero-volume end. The comparison allowance of 1e-4 percentage points handles numerical volume rounding; it is not clinical uncertainty. Producer output is checked before plots/reports and again at the post-tool boundary.
- DVH histogram step starts at 0.01 Gy and increases to respect the 10,001-bin budget. Read each `bin_width_Gy`. Histogram step, voxel size and clinical uncertainty are different quantities. D95 is a dose-volume percentile, not a percentage of prescription. V50 is V50Gy in percent/cc.
- Gamma is discrete global nearest-neighbour search, without interpolation. Nearest-candidate distances are recomputed from direct physical dose/coordinate differences in float64; dose normalization is `reference_max * tolerance_percent / 100`. Passing uses unrounded gamma <= 1, with **zero extra numerical acceptance tolerance**. `threshold_policy`, `average_gamma_unrounded` and `max_gamma_unrounded` record this contract; existing rounded fields are display values only. Machine-precision ties still need commissioning across supported runtimes, separate from clinical error margins.
- TOPAS dimensions and energies use 17 significant digits to preserve accepted binary-float values, including small positive dimensions. Templates do not establish runtime/geometry/transport commissioning; inspect the actual deck and qualify the installed TOPAS/Geant4/data versions.

Read intake findings, source/course identity, uncertainty and scope together. A valid selected-ROI metric does not release a blocked case. Actual prescription, fractionation and endpoint-specific reviewed OAR constraints are required. Naming cannot establish anatomy. `APPROVED` means a per-case research candidate only; caller-hashed calibration files are not independently certified evidence.

## Evidence and recovery

```bash
python -m validation.benchmarks.stress.stress_all_menus --require-complete --output-dir /separate/new-evidence-directory
```

Use a source-only isolated checkout/work directory and authorized read-only inputs. `--require-complete` makes any skipped or failed scenario fail qualification. Exploratory partial runs remain explicit; exit 0 there is not qualification. Publication is refused for incomplete/failed runs. Output ownership is reserved before any work; existing evidence needs explicit `--force-overwrite`, and the default reviewed snapshot is preserved unless `--publish-evidence` is requested. Publication still requires privacy and scientific review.

Trajectory events use a typed versioned schema. Extra metadata cannot replace reserved timestamp/prompt/response/version fields. Valid legacy events remain readable. Corrupt history is preserved and refused; failed atomic replacement preserves old bytes and cleans temporary files. POSIX locking and directory/file synchronization protect the local store, not independent hosts or ephemeral-container survival. Keep backups and retention policy; production needs authenticated durable transactions, external audit anchoring and tested recovery.

## Remaining release gates

1. **Shared research:** authenticate identities and session ownership, constrain input access, provide durable multi-instance artifacts/metadata/audit, isolated bounded workers, complete operation logging, reviewer-key lifecycle, backup/restore and external chain-head anchoring.
2. **Scientific/clinical:** independent model-bound qualification and representative cohorts, registered masks/reference provenance, measured comparisons where applicable, calibrated OOD/uncertainty/confidence, actual clinical protocols and qualified independent physicist adjudication. Auto-segmentation and Monte Carlo transport need their own validated workflows.
3. **Reproducibility:** qualify exact supported-runtime dependency/container resolutions. A recorded freeze is evidence of one environment, not a portable hash-locked distribution or vulnerability-free guarantee.

See [rectification evidence and dispositions](../validation/evidence/rectification/README.md), [decision contract](DECISION_ENGINE.md), and [local workflows](LOCAL_WORKFLOWS.md). Raw patient inventories, diagnostic logs and credentials must remain outside public evidence.

Core dose tools and dynamic copilot runs now append local `operations.jsonl` start/return/error outcomes with correlation IDs and output digests. Prompts, arguments, credentials, result contents and exception messages are excluded. Nested calls share their active session. Audit failures propagate instead of returning a claimed committed success. This improves local traceability but does not supply authentication, cross-instance durability, complete HTTP access logging or external anchoring.

### pydicom security backport

The dependency is pinned to pydicom **2.4.5**, preserving the legacy dicompyler comparison while requiring the maintainer's CVE-2026-32711 containment backport. The [maintainer advisory](https://github.com/pydicom/pydicom/security/advisories/GHSA-v856-2rf8-9f28) lists 2.4.5 and 3.0.2 as patched; the [2.4.5 release](https://github.com/pydicom/pydicom/releases/tag/v2.4.5) records the backport. A public FileSet traversal regression uses generated nonpatient files and verifies refusal without touching the outside file. The current vulnerability feed still flags 2.4.5; that narrow discrepancy is recorded with evidence, rather than treating every scanner result as either a confirmed exploitable defect or a clean bill of health.

## Patient export boundaries

See [patient-data QA and common export errors](PATIENT_DATA_QA.md) for the implemented refusal policy, source geometry handling, dose summation scope and a reproducible read-only fault campaign. Source association and unsupported geometry are checked before the minimal analysis projection can hide them.
