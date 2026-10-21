# Copilot and full-corpus stress checks

All generated runs go under ignored `validation/runs/`. Reviewed public summaries belong in `validation/evidence/`; never publish raw clinical files or credentials.

- `python -m validation.benchmarks.stress.datasets`: Explicit opt-in full SlicerRT download (6,966 files, approximately 5.2 GB). Pinned Git blob hashes are checked; existing files are never overwritten. Source data remains ignored. No source redistribution permission is inferred.
- `python -m validation.benchmarks.stress.audit_all`: Read-only intake of all 45 public collections and the three specifically authorized local case folders. Runs the actual copilot intake locally, hashes sources before and after, and retains pseudonymous detailed reports locally. Edit the explicit local source configuration for a different installation. This is compatibility/intake testing; blocked cases are not forced through DVH or interpreted as model accuracy evidence.
- `python -m validation.benchmarks.stress.numerical`: 1,450 deterministic synthetic numerical checks with a fixed seed and analytical endpoint/gamma oracles.
- `python -m validation.benchmarks.stress.live_copilot`: Four bounded synthetic Gemini cases. Prompts for a hidden credential, held only in process memory. No patient input goes to Gemini. Availability, authentication and quota failures are recorded as failures, never simulated success. Requires a real interactive terminal.
- `python -m pytest validation/tests -q`: Offline physics, API, UI, governance and provider fault-injection regressions, including concurrent session isolation.

Live model responses are nondeterministic; a passing synthetic demonstration is not a clinical validation or a guarantee of provider uptime. Full-corpus folders contain unsupported modalities, legacy encodings and non-DICOM assets. Local intake intentionally blocks malformed contours and unresolved coordinate associations rather than altering sources.

For qualification, use `python -m validation.benchmarks.stress.stress_all_menus --require-complete --output-dir /separate/new-run`. It reserves output before tool work, refuses concurrent ownership, atomically commits evidence and fails skipped/failed scenarios. Exploratory runs may be PARTIAL; they do not pass qualification. Publication refuses incomplete/failed evidence and still requires human privacy/scientific review. See [operating instructions](../../../docs/HARDENING.md).
