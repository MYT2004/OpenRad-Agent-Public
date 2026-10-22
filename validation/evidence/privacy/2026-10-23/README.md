# Repository privacy review — 23 October 2026

## Current published files

Two personal absolute paths were removed: the full-corpus benchmark now reads `OPENRAD_LOCAL_DATA_ROOT` (default `data/raw`), and an existing stress result retains only its relative `storage/` artifact path. Numerical results and statuses were unchanged. Missing benchmark collections now stop the run explicitly; configure the local data parent before running `python -m validation.benchmarks.stress.audit_all`.

A scan of 203 tracked files and 418 reachable historical blobs found no matches for Google API keys, the supplied credential's key format, GitHub tokens or private-key headers. Commit messages were also checked for these credential patterns, personal names and email addresses. These are pattern-based checks, not a guarantee that arbitrary secrets can never be present. Generic home-directory examples in security tests and path-redaction code are intentional and contain no actual user home path.

All 33 tracked DICOM files have synthetic teaching patient names and IDs. Raw clinical collections, local environment configuration, session outputs and private working reports are ignored rather than published. Public dataset case identifiers and the public GitHub account handle are intentional references.

## Validation

All 377 regression tests passed (five existing dependency/invalid-fixture warnings). A focused missing-input check confirmed that the full-corpus benchmark refuses absent collections before invoking patient processing. The five tracked PNG figures/screenshots were visually reviewed and contain no visible personal identifiers. These checks did not edit raw data.

## Historical exposure remains unresolved

Earlier reachable file revisions contain the removed personal paths. A personal email address also exists in author/committer metadata. Current-file cleanup cannot remove either from Git history. No history rewrite or force push was performed: that would change published commit IDs and requires separate coordination. GitHub cached views, pull-request references and other clones may require additional cleanup even after a rewrite.

Sensitive matched values are deliberately omitted from this public report. This review does not certify the entire GitHub history as free of personal information.
