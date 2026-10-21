# Medical physicist workflow verification

This audit covers the repository pulled through `4a4a637`, followed by fixes to execution, reporting and safety discrepancies. It is a software verification exercise, not commissioning or a certificate of clinical/regulatory conformity.

## Workflow evidence and useful outputs

| Workflow | Executed verification | Human-facing output | Interpretation boundary |
|---|---|---|---|
| DICOM discovery / DVH | Synthetic known-dose DICOM; supplied local datasets; comparison with dicompyler-core | Structure metrics with Gy/cc/% units, cumulative DVH, linkage status, partial-result errors, Markdown/CSV/JSON downloads | Supported axial sampling only. Naming does not establish anatomy. No plan pass without prescription and protocol constraints. |
| Gamma | Analytic constant offset; brute-force comparison; in-memory/file, API and UI paths | Criteria and cutoff, passing rate, eligible/total voxel count, policy band and follow-up actions | Discrete global gamma without interpolation or a measurement-uncertainty model. High aggregate pass rate does not localize clinical errors. |
| TOPAS | Supported particle/phantom templates, bounds and no-clamping rejection, CLI/API/agent/UI paths | Parameter file, handoff report, particle, MeV, histories, seed/thread values and scoring quantity | TOPAS is unavailable locally; transport execution, physical accuracy and beam commissioning remain unverified. |
| LKB NTCP / Poisson EUD TCP | Analytic 50% endpoint examples; bounds and malformed DVH rejection; API/UI paths | Percentage estimate, EUD in Gy, parameter record and applicability limits | No fractionation conversion, parameter confidence interval or endpoint-specific patient outcome validation. `Poisson_LQ` is a legacy API name, not an implemented full LQ survival/fractionation calculation. |
| Model assessment | Threshold boundaries, bad dose/masks/geometry, absent evidence, signed reviews and source hashing | Rule evidence, prescription and errors in Gy/%, difference/uncertainty maps, overlaid DVHs, downloadable report | Per-case research triage. Registration is caller-declared; calibration files are hashed rather than scientifically certified. Segmentation needs a separate validated policy. |
| In-memory model preflight | Negative epsilon, nonfinite values, invalid dimensions/masks/uncertainty, OAR matching and missing reference | Explicit failures/review triggers, computed gamma or “Not evaluated”, unsigned integrity digest | Always requires full provenance/qualification review; it cannot independently approve a model or treatment. |
| Agent routing / REPL | Explicit typed tools, unsupported task responses, photon/TOPAS routing, artifact retrieval, state persistence and multiple dose-array checks | Readable tool results and correctly retrievable report/deck/plot artifacts | Deterministic routing, not an autonomous clinical decision maker. REPL is trusted unrestricted Python; post-execution checks do not make it a security sandbox. |
| Multimodal readers | Actual synthetic JSON, CSV, text, DICOM and PDF files, including absent/corrupt input paths | Local extracted text/metadata and readable errors | Extracted document content is data, not instructions. These readers are not PHI-scrubbing exporters or automatic clinical interpretation. |

All workflows preserve detailed machine-readable evidence. UI assessment views provide Markdown reports, CSV metrics and JSON technical downloads; TOPAS also provides its parameter file. Results persist through downloads and are hidden when their input fields change. A new calculation is required for changed inputs.

## Corrections made

- Restored Python 3.9 imports using postponed annotation evaluation. Constrained pydicom to the tested 2.4.x API because the tested dicompyler-core 0.5.6 imports `read_file`, [removed in pydicom 3](https://pydicom.github.io/pydicom/dev/release_notes/v3.0.0.html).
- Removed automatic anatomical alias adoption. Suggested mappings are scoped to the source structures and require anatomical confirmation; explicit mappings remain available. Missing/unknown names are review requirements, not automatic declarations of TG-263 noncompliance.
- Corrected gamma terminology: [TG-218](https://www.aapm.org/pubs/reports/detail.asp?docid=173) reference criteria are global 3%/2 mm, 10% cutoff, with 95% tolerance and 90% action limits. The additional 3%/3 mm and 2%/2 mm bands are custom research policies.
- Removed fabricated 100% gamma defaults and generic OAR limit application from the in-memory preflight. Exact supplied masks/limits replace substring matching. Negative doses have zero tolerance. Missing evidence stays unresolved.
- Removed unsupported claims of digital signatures, HIPAA compliance, TG-53 conformity, lethal toxicity and clinical release from generated assessments. A hash is an integrity digest; signed reviewer dispositions use the separate Ed25519 workflow.
- Fixed output-path checks to reject raw roots/symlinks before creating directories. Removed redundant DVH writes into the application source tree, preserving Cloud Run operation with only session storage writable.
- Made reports/decks/plots accessible through restricted artifact names. Tool audit append failures now surface instead of being silently ignored. The REPL checks all named dose arrays, rather than only the first.
- Removed the example that silently clamped an out-of-range beam energy. The DVH demo now requires explicitly supplied data and structures instead of substituting a built-in patient or radiobiology parameter set.

## Local data evidence

Before/after SHA-256 comparisons covered 1,318 files across the three user-supplied local folders, including 1,309 DICOM files. All hashes were unchanged. Four UID-linked dose/plan/structure pairs were discovered. Two pairs remain blocked by frame/linkage discrepancies; no registration or source correction was inferred.

Three supported structure comparisons against dicompyler-core had maximum absolute discrepancies of approximately 0.040 Gy for D95 and 0.032 Gy for mean dose. This small selected set does not establish a general error bound, validate all contours, or commission the sampler. Unsupported/self-intersecting contours remain blocked. Detailed local reports and patient-derived artifacts are ignored by Git and are not uploaded.

## Verification commands

```bash
python -m pytest tests -q
python agent_main.py --help
python -m examples.topas_generation_demo
python -m examples.dvh_analysis_demo /authorized/read-only/dataset --roi Brainstem
python -m scripts.verify_local_datasets /authorized/read-only/dataset --reference
```

The local test suite has 181 passing tests. GitHub CI additionally exercises Python 3.11, Docker image construction and live FastAPI `/health`. The local environment lacks Docker and TOPAS. Unit/API/UI tests are useful evidence but cannot demonstrate every possible input or replace independent clinical commissioning and usability assessment by practicing medical physicists.

Use OS/container read-only mounts for raw data, IAM/authentication for deployment, durable audit storage with external anchoring and an independently managed reviewer registry. Those deployment controls, calibrated OOD detection, anatomical validation, clinical uncertainty budgets and physical measurements remain prerequisites for consequential use.
