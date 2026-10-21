# OpenRad-Agent — OSI Hackathon

A deterministic research proof of concept for DICOM-RT dose-volume analysis and TOPAS input generation. The FastAPI server and CLI share real tools, session storage, metadata scrubbing and mandatory physics checks. Clinical commissioning and regulatory conformity are not established; see [the physics audit](MEDICAL_PHYSICS_AUDIT.md).

## Repository layout

```text
server.py                    FastAPI REST entry point for Cloud Run
agent_main.py                CLI entry point
src/
  decision.py                Typed research triage contract and policy
  evaluation.py              Read-only comparison, metrics and plots
  governance.py              Hash chained audit and Ed25519 review
  tools.py                   Canonical DVH and TOPAS tools
  storage.py                 Session and artifact management
  hooks.py                   Enforced @post_tool_call validation
  privacy.py                 Minimal scrubbed DICOM analysis copies
  config.py                  Shared relative skills_paths
openrad/                     Deterministic physics and nomenclature engine
frontend/app.py              Optional local Streamlit UI
tests/                       Automated tests and reader smoke runner
skills/radiation_physics/    Physics workflow instructions
SKILL.md                     Entry-point execution policy
storage/sessions/            Runtime outputs only; ignored by Git
```

The repository is already flat; there is no inner `OpenRad-Antigravity-Agent/` project. Root `README.md` is the canonical project guide. `requirements.txt` installs the extras defined in `pyproject.toml` rather than maintaining another dependency list.

## Install and verify

Python 3.9+ is supported by the project; the Cloud Run image uses Python 3.11.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests -q
```

## CLI

```bash
python agent_main.py dvh --rtdose /input/dose.dcm --rtstruct /input/struct.dcm --rtplan /input/plan.dcm --roi Brainstem
python agent_main.py topas --particle proton --energy-mev 150 --histories 100000
```

Use `--storage-dir` and `--session-id` before the subcommand to choose a session. `dvh --roi-map '{"Cord":"SpinalCord"}'` accepts explicitly human-reviewed legacy ROI mappings. The CLI emits JSON and exits with code 2 for failed or incomplete analyses. `topas --output output.txt` selects a destination; existing files are not overwritten.

The public Python interfaces are:

```python
from src.tools import parse_and_evaluate_dvh, generate_topas_file
from src.storage import StorageManager, session_scope

manager = StorageManager("storage/sessions")
with session_scope(manager, "demo"):
    result = parse_and_evaluate_dvh("dose.dcm", "struct.dcm", ["Brainstem"], rtplan_path="plan.dcm")
    deck = generate_topas_file("proton", 150.0, 100000, "storage/sessions/demo/artifacts/topas.txt")
```

`parse_and_evaluate_dvh` uses pydicom for DICOM/contours and the public PyMedPhys dose/coordinate API. It reports D95%[Gy], D50%[Gy], D2%[Gy], V50Gy[%], V50Gy[cc] and mean dose. It saves cumulative DVH PNGs under the active session. The three positional arguments work without RTPLAN, but course linkage is then explicitly unverified. Supply RTPLAN for full dose→plan→structure association checks.

## REST server and Cloud Run

```bash
PORT=8080 python server.py
```

The server listens on `0.0.0.0` and the dynamic `PORT` environment variable (default 8080), as required by [Cloud Run's container contract](https://docs.cloud.google.com/run/docs/container-contract). Use `CORS_ORIGINS` for a comma-separated list of authorized frontend origins; credentialed wildcard CORS is not enabled.

- `GET /health` — readiness metadata and shared skill paths.
- `POST /api/v1/dvh/analyze` — `rtdose_path`, `rtstruct_path`, `rois`, optional `rtplan_path`, `reviewed_name_map`, `session_id`.
- `POST /api/v1/topas/generate` — `particle`, `energy_mev`, `histories`, optional `session_id`.
- `GET /artifacts/{session_id}/artifacts/{filename}` — generated DVH PNGs or TOPAS text; session trajectories are not publicly mounted.
- Existing gamma, radiobiology, agent and session endpoints remain available. Older DVH/TOPAS field names are accepted as aliases.

```bash
docker build -t openrad-osi .
docker run --rm -p 8080:8080 -e PORT=8080 openrad-osi
```

The image runs as a non-root user. `.dockerignore` and explicit Docker copies exclude patient datasets, secrets and runtime sessions. Cloud Run storage defaults to `/tmp/openrad/sessions` and is ephemeral. Mount authorized, appropriately de-identified input files separately; do not bake patient records into the image. Use Cloud Run IAM authentication before any network deployment with sensitive data. This refactor does not deploy a service or provision durable storage.

Both entry points use `skills_paths = ["./skills/radiation_physics", "./SKILL.md"]`. Run from the repository root; the image uses `/app` as its working directory.

## Model evaluation and signed review

The CLI `evaluate --manifest evaluation.json`, REST `POST /api/v1/evaluations`, and frontend Model Evaluation & Triage workflow compare supplied dose arrays against a reference. Three-way triage records physical checks, gamma, PTV/OAR/MAE thresholds, uncertainty/OOD evidence and SHA-256 provenance. Signed reviewer dispositions preserve the automated result. `APPROVED` is a per-case research candidate, with `clinical_release=false`. Raw sources are read-only. See [the contract, exact thresholds, review protocol and remaining validation gaps](docs/DECISION_ENGINE.md).

## Optional frontend

```bash
streamlit run frontend/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

The local UI can discover UID-linked datasets and route DVH requests through `src.tools`. Configure local folders in the sidebar or ignored `.env`. See [local workflows](docs/LOCAL_WORKFLOWS.md) and [TG-263 implementation scope](docs/TG263.md).

## Safety and privacy scope

Patient identity is checked before scrubbing so anonymisation cannot hide a wrong-patient match. Only required numeric geometry, pixels and contours are copied into analysis datasets; private tags, demographics, dates, free text and original identifying UIDs are excluded or replaced. Unsupported names are replaced with generic ROI labels; recognized TG-263 names are retained. Original DICOMs remain unchanged. This is an in-memory analysis projection, not a general de-identification exporter or certification of DICOM confidentiality-profile compliance. Burned-in annotation is rejected for dedicated review.

The enforced `@post_tool_call` hook rejects negative/nonfinite doses and array/axis shape corruption. Beam energy must be 0.01–250 MeV and histories must be positive integers. TOPAS files contain World, Physics, BeamPosition, source and scorer definitions, but require validation in an installed TOPAS runtime.

The axial DVH sampler rejects frame mismatches, unsupported topology, oblique/nonuniform grids, irregular contour planes and incomplete coverage. No measurements or prescriptions are silently changed. Gamma needs independent measurements; radiobiology needs explicit endpoint-specific parameters. The trusted local REPL is not a security sandbox. Clinical release and uncertainty budgets remain open work.
