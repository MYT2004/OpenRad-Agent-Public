# OSI 2026 sponsor track evidence

Checked 23 October 2026. The [submission rules](https://llmhackathon.github.io/submission/) require actual platform use for sponsor tracks.

| Track | Supported selection | Evidence and scope |
| --- | --- | --- |
| Valency MCP Bond | Yes: literature discovery and reference verification | Connected Valency MCP search was used to locate research references and public benchmark candidates. Existing records are in [patient-file verification](../PATIENT_FILE_VERIFICATION.md) and [the specification](../HACKATHON_SPECIFICATION.md). A repeat OpenKBP title search is recorded below. |
| marimo | Leave unticked | No marimo notebook, dependency, configuration or documented tool use was found in the tracked repository. |
| Adaption | Leave unticked | No Adaption integration, dependency, configuration or documented tool use was found in the tracked repository. |

Valency supports the project's research workflow. It is not integrated into the app's numerical runtime, does not calculate DVHs or gamma, and does not certify clinical safety. Sponsor eligibility remains the organisers' decision.

## Reference verification

On 23 October 2026, the connected Valency `search_by_title` tool (server version 0.4.1) was called with query `OpenKBP`, limit 3, semantic fallback disabled, without a source restriction. Returned references included:

- [OpenKBP: The open-access knowledge-based planning grand challenge](https://arxiv.org/abs/2011.14076), DOI `10.1002/mp.14845`.
- [OpenKBP-Opt: an international and reproducible evaluation of 76 knowledge-based planning pipelines](https://pubmed.ncbi.nlm.nih.gov/36093921/), DOI `10.1088/1361-6560/ac8044`; the corresponding [preprint](https://arxiv.org/abs/2202.08303) was also returned.

The response included a no-strong-matches warning. Returned titles and identifiers were used for bibliography verification, not as evidence that OpenRad has reproduced these studies or evaluated their full datasets. No private inputs were included in this query.

## Reproduction and configuration

A clone runs without a Valency account. Repeating literature discovery requires an independently authenticated [MCP Bond connection](https://www.valency.io/bond/) in an MCP-compatible assistant. No account tokens or credentials are distributed in this repository.
