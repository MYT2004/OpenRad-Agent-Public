# Audit rectification dispositions

22 October 2026. IDs refer to the 63822e9 audit. Fixed is limited to the reproduced software case and retained scope; open qualification requirements are not hidden.

| ID | Disposition | Implementation/evidence or remaining work |
|---|---|---|
| N01 | Fixed | Numeric NPY dtype/header preflight; generic parse errors; Unicode/byte/object marker API regressions. |
| N02 | Fixed | Complete DVH validation before reports/plots and in the post-tool hook; injected producer failure publishes no artifacts. |
| N03 | Fixed | Scalar/None/ragged/overflow/nonnumeric curves return safe structured failures. |
| N04 | Implemented/tested policy | Direct physical differences, unrounded fields, zero extra gamma acceptance tolerance; 96/96 oracle controls agree. Clinical commissioning remains separate. |
| N05 | Fixed | Typed versioned history; reserved-field override refusal; atomic metadata/history and temporary cleanup. |
| N06 | Fixed | 17 significant-digit serialization and underflow rejection; positive half-length/layer controls. |
| N07 | Fixed | Nonboolean numeric energy across shared guard, generators, agent/model schemas and REST. |
| N08 | Fixed | README documents adaptive minimum 0.01 Gy histogram step and its bin budget. |
| N09 | Fixed | Physical dose invariant cannot be relaxed by a negative tolerance. |
| R05 | Fixed qualification gate | --require-complete and publication completeness checks; exploratory partial runs remain explicit. |
| R07 | Partly addressed | Header/file/voxel bounds and per-process admission; distributed isolated workers, hard cancellation/timeouts and capacity qualification remain required. |
| R08 | Open shared-use gate | Single trusted operator profile only; identity/tenant ownership and deployed IAM/input access need an approved implementation. |
| R09 | Open shared-use gate | Local atomic commits/locks improved; durable cross-instance storage, backup/recovery and retention are not supplied. |
| R10 | Open if untrusted code is exposed | Trusted in-process REPL remains outside an OS sandbox; do not expose it to untrusted callers. |
| R11 | Partly addressed | Core tools/copilot append redacted start/return/error outcomes and digests; durable authenticated HTTP/operation audit and external anchoring remain required. |
| R12 | Open scientific gate | Independent candidate cohorts, physical references where applicable, uncertainty/OOD calibration and expert commissioning require external evidence. |
| R13 | Partly addressed | Python 3.11+ support, 3.11/3.13 CI matrix, fresh 3.13 tests, pinned patched pydicom and resolved environment evidence; portable hash locking and broader qualification remain. |
| R15 | Fixed interpretation scope | Selected-ROI harness explicitly does not clear whole-case blockers; no unreviewed 45 Gy clinical constraint inference. |
| R16 | Fixed API semantics | REST reports deterministic mode and rejects ignored hosted model selection; provider remains a separate explicit workflow. |
| R17 | Fixed | Canonical policies packaged, synchronized by test and loaded independently of working directory; installed-wheel smoke passes. |
| R19 | Open production gate | External chain-head anchoring, authenticated durable retention and reviewer-key lifecycle still require infrastructure. |
| R20 | Open scientific gate | Hashed caller-supplied files remain explicitly unqualified; independent model-bound certification cannot be manufactured in code. |
| R21 | Fixed | Output reservation before workload, collision lock and atomic evidence commit; explicit overwrite/publication controls retained. |

Additional hardening: generated FileSet traversal security regression, session/artifact symlink boundaries, shared ASGI-profile refusal, typed API energy, redacted operation failures and overload/retry checks. No patient source files were changed.
