# OpenRad-Agent — OSI Hackathon 2026

[![Physics regression](https://github.com/MYT2004/OpenRad-Agent/actions/workflows/physics-regression.yml/badge.svg)](https://github.com/MYT2004/OpenRad-Agent/actions/workflows/physics-regression.yml)
[![Physics Guardrails: Enforced](https://img.shields.io/badge/physics--guardrails-strictly%20enforced-blue.svg)](openrad/validation/physics_rules.py)
[![Standards: TG--263%20%7C%20TG--218](https://img.shields.io/badge/standards-TG--263%20%7C%20TG--218-purple.svg)](openrad/validation/nomenclature.py)
[![Scope: Research Only](https://img.shields.io/badge/scope-research%20use%20only-orange.svg)](validation/audits/medical_physics.md)

**OpenRad Agent** is an autonomous medical physics evaluation harness and clinical research copilot. Designed for radiotherapy AI model verification, computational dose assessment, and quality assurance, OpenRad provides deterministic dosimetric calculation engines coupled with grounded LLM reasoning.

> [!WARNING]
> **RESEARCH USE ONLY — NOT FOR CLINICAL RELEASE**
> Single-case research candidate evaluation only. Does not replace independent clinical commissioning, certified treatment planning systems (TPS), or clinical physicist sign-off.

---

## OSI Hackathon 2026: start here

New evaluators should use the [complete judge's guide](docs/osi-hackathon-2026/JUDGES_GUIDE.md): a five-minute synthetic tour, all nine menus, exact input examples, expected refusals, status meanings and troubleshooting. It was checked against code revision `7f09598`.

After installing the project from this repository root, launch the bundled teaching case:

```bash
OPENRAD_DATA_ROOTS='["data/demo/01_clean_case"]' \
STORAGE_DIR='./storage/sessions' \
python -m streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501
```

Open `http://127.0.0.1:8501/`, verify the clean case, then use its **Continue to DVH and structure review** handoff. The guide also shows deliberately blocked cases and 100%/0% synthetic gamma controls. No Gemini key or patient-data download is needed for this tour. `READY_FOR_RESEARCH_ANALYSIS` means intake readiness; `APPROVED` in model triage means a supplied-case research candidate. Neither approves treatment.

The latest [efficiency audit](validation/evidence/efficiency/2026-10-23/README.md) records 377 passing regressions, 28 complete workflow scenarios and 1,450 numerical checks. Its 26.2% reduction in peak traced gamma allocation retained identical tested results; it is not an accuracy gain or a general speedup.

**Data acknowledgements:** local HNSCC testing uses the [Zenodo distribution](https://zenodo.org/records/5276878) of the original [TCIA HNSCC dataset](https://doi.org/10.7937/k9/tcia.2020.a8sh-7363); external test collections come from [SlicerRtData](https://github.com/SlicerRt/SlicerRtData). See [data sources, required references and access notes](docs/DATA_SOURCES.md). Packaged `data/demo/` files are separate OpenRad-generated synthetic fixtures.

---

## 1. System Architecture

```mermaid
flowchart TD
    subgraph UI ["User Interfaces"]
        direction TB
        Streamlit["Streamlit Dashboard<br/>(frontend/app.py)"]
        FastAPI["FastAPI REST Engine<br/>(server.py)"]
        CLI["CLI Toolset<br/>(agent_main.py)"]
    end

    subgraph DualModes ["Operational Execution Pathways"]
        direction TB
        Mode1["Mode 1: Deterministic Assessment Router<br/>(Fail-Closed Safety Triage)"]
        Mode2["Mode 2: Dynamic LLM Copilot Prototype<br/>(Google GenAI / Gemini Function Calling)"]
    end

    subgraph PhysicsEngine ["Physics Guardrails & Validation Engine"]
        direction TB
        Preflight["Pessimistic Safety Interceptors<br/>(openrad.validation.physics_rules)"]
        DoseCheck["Dose Non-Negativity: D(r) >= 0.0 Gy"]
        EnergyCheck["Beam Kinetic Bounds: 0.01 <= E <= 250 MeV"]
        GeomCheck["Orthogonal Direction Cosines & Positive Spacing"]
        CordCheck["Reviewed protocol-specific constraints required"]
    end

    subgraph DeterministicTools ["Grounded Medical Physics Toolset"]
        direction TB
        DVH["ICRU-83 DVH Analyzer & TG-263 Nomenclature<br/>(openrad.tools.dicom_tool)"]
        Gamma["AAPM TG-218 3D Gamma QA Engine<br/>(openrad.tools.gamma_tool)"]
        TOPAS["TOPAS / Geant4 Monte Carlo Generator<br/>(openrad.tools.topas_tool)"]
        Radiobio["LKB NTCP & Poisson TCP Models<br/>(openrad.tools.radiobio_tool)"]
        Intake["Patient-File Integrity & Linkage Verifier<br/>(src.case_verification)"]
    end

    subgraph Outputs ["Provenance, Audit & Reporting"]
        direction TB
        Audit["SHA-256 Hashes & Ed25519 Review Signatures"]
        Reports["Synthesized Clinical Reports & Reasoning Trajectory"]
        Storage["Separated Session Storage (data/processed/ & storage/sessions/)"]
    end

    UI --> DualModes
    Mode1 --> Preflight
    Mode2 --> Preflight
    Preflight --> DoseCheck & EnergyCheck & GeomCheck & CordCheck
    DoseCheck & EnergyCheck & GeomCheck & CordCheck --> DeterministicTools
    DeterministicTools --> Outputs
```

---

## 2. Dual Operational Modes

OpenRad Agent bridges safety-critical deterministic computing with modern tool-augmented language model reasoning:

### Mode 1: Deterministic Assessment Router (Clinical Safety Pathway)
* **Design aim:** Fail-closed research triage with explicit errors and unsupported states; no error-free or clinical-release guarantee.
* **Deterministic Execution:** Direct, typed module execution (`src/case_verification.py`, `src/tools.py`, `src/evaluation.py`, `src/decision.py`).
* **Three-Way Triage Decisions:** Hard rules determine `APPROVED` (per-case research candidate), `FLAGGED_FOR_REVIEW`, or `REJECTED`.
* **Cryptographic Provenance:** Ed25519 signature verification and SHA-256 hash chaining provide signed decisions and tamper-evident audit records.

### Mode 2: Dynamic LLM Copilot Prototype (Interactive Research Partner)
* **Design Philosophy:** Tool-augmented reasoning via **Google GenAI / Gemini Function Calling** (`src/agent_dynamic.py`).
* **Grounded Function Calling:** The LLM does not perform mathematical or dosimetric calculations in-text. All numbers, metrics, and plan decisions originate from deterministic tools (`tool_verify_case_intake`, `tool_compute_dvh_metrics`, `tool_evaluate_tg218_gamma`, `tool_generate_topas_deck`).
* **Pessimistic Safety Interceptors:** Validates all parameters before execution. If negative dose arrays ($D(\vec{r}) < 0\text{ Gy}$) or out-of-bound energies are detected, the tool call is rejected before running.
* **Clinical limits:** Require a reviewed protocol with prescription and fractionation. No universal 45 Gy spinal cord limit or clinical approval is inferred.
* **Tool action recording:** Captures selected tools and deterministic observations; private model reasoning is not exported.
* **Explicit offline mode:** Without a key, performs local intake only. Provider errors stop the run without simulated measurements.

---

## 3. Verified Validation Milestones

### Automated regression and boundary validation
Current revision-specific test counts and supported-runtime results are recorded in CI and the [rectification evidence](validation/evidence/rectification/README.md). The suite covers:
* **DICOM Intake & Spatial Geometry:** Slice spacing regularity, UID chain linkage, orthogonal direction cosines, and metadata de-identification.
* **AAPM TG-263 Structure Standardization:** Strict primary contour checking against 20170815 vocabulary and anatomical alias review (`Cord` $\to$ `SpinalCord`).
* **ICRU-83 Dosimetric Metrics:** Adaptive cumulative DVH binning (minimum $0.01\text{ Gy}$ step, enlarged when needed to stay within 10,001 bins): $D_{95}$ (minimum dose received by at least 95% of structure volume), $D_{50}$ (median dose), $D_{2}$ (near-max dose), $V_{50\text{Gy}}$, $\bar{D}$, and $D_{\max}$.
* **AAPM TG-218 3D Gamma Index:** Global 3% / 2 mm (with 10% low-dose threshold) and tight-margin 2% / 2 mm QA evaluation.
* **TOPAS Parameter Validation:** Kinetic beam energies constrained to $0.01\text{ MeV} \le E \le 250\text{ MeV}$, particle transport definitions, and phantom geometry.
* **Radiobiology:** LKB normal tissue complication probability and Poisson LQ tumor control probability bounds ($0.0 \le P \le 1.0$).

### SlicerRtData External Benchmark (3-Way Cross-Comparison)
Evaluated on public SlicerRt reference datasets against Eclipse TPS (Varian) and `dicompyler-core`:

| Structure | Metric | Eclipse TPS Export | OpenRad Calculation | dicompyler-core | $\Delta$ (OpenRad vs Eclipse) | $\Delta$ (OpenRad vs dicompyler) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Bladder** | Volume | 116.800 cc | 117.453 cc | 117.453 cc | +0.653 cc (+0.56%) | -0.0001 cc |
| | Mean Dose | 45.908 Gy | 45.870 Gy | 45.872 Gy | -0.038 Gy (-0.08%) | -0.0019 Gy |
| | D95% ($D_{95}$) | 43.661 Gy | 43.610 Gy | 43.590 Gy | -0.051 Gy (-0.12%) | +0.020 Gy |
| **PTV** | Volume | 48.600 cc | 49.094 cc | 49.094 cc | +0.494 cc (+1.02%) | +0.0003 cc |
| | Mean Dose | 45.862 Gy | 45.880 Gy | 45.881 Gy | +0.018 Gy (+0.04%) | -0.0012 Gy |
| | D95% ($D_{95}$) | 45.360 Gy | 45.350 Gy | 45.350 Gy | -0.010 Gy (-0.02%) | 0.0000 Gy |
| **Rectum** | Volume | 30.300 cc | 30.516 cc | 30.516 cc | +0.216 cc (+0.71%) | +0.0004 cc |
| | Mean Dose | 39.146 Gy | 39.050 Gy | 39.046 Gy | -0.096 Gy (-0.25%) | +0.0037 Gy |
| | D95% ($D_{95}$) | 28.061 Gy | 27.690 Gy | 27.690 Gy | -0.371 Gy (-1.32%) | 0.0000 Gy |

> **Key Finding:** OpenRad calculation exhibits close mathematical concordance with `dicompyler-core` default voxel rasterization (volume $\Delta \le 0.0004\text{ cc}$, dose $\Delta \le 0.020\text{ Gy}$). Differences relative to Eclipse TPS summary export ($+0.653\text{ cc}$ in bladder volume, $-0.371\text{ Gy}$ in rectum $D_{95}$) are hypothesized to arise from proprietary contour voxelization, sub-slice contour interpolation, and dose-bin interpolation algorithms. In accordance with clinical physics best practices, commercial TPS exports and third-party tools serve as numerical comparators rather than certified clinical ground truth.

---

## 4. Repository Layout

```text
app.py                       Streamlit unified launcher (forwards to frontend/app.py)
agent_main.py                CLI entrypoint for all medical physics subcommands
server.py                    FastAPI REST entry point for Cloud Run deployment
src/
  agent_dynamic.py           Dynamic LLM Copilot with Gemini Function Calling & Trajectory Logging
  case_verification.py       Patient file intake, UID verification, geometry and pixel checks
  decision.py                Typed research triage contract, policy matrix, and thresholds
  evaluation.py              Dose comparison, gamma analysis, DVH metrics, and plot generation
  governance.py              Ed25519 signature review and SHA-256 audit chaining
  tools.py                   Deterministic DVH sampling, TOPAS generator, and safe path resolvers
  storage.py                 Isolated session manager and artifact directories
  privacy.py                 Minimal in-memory scrubbed DICOM projections
  hooks.py                   Enforced post-tool-call physics guardrails
openrad/                     Core medical physics and AAPM TG-263 nomenclature engine
frontend/app.py              Streamlit interactive clinical QA & copilot dashboard
validation/                  Regression tests, benchmarks, physics audits, and evidence
skills/radiation_physics/    Medical physics mathematical formulations and workflow rules
```

---

## 5. Installation & Execution

### 1. Environment Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Run the Full Test Suite
```bash
pytest validation/tests/ -v
```

### 3. Launch the Interactive Streamlit Dashboard
```bash
streamlit run app.py --server.port 8501
```
Port **8501** is the standard local dashboard port and is also configured in `.streamlit/config.toml`. Run from the repository root and stop any previous OpenRad instance using this port before starting another. Open `http://localhost:8501` to access:

1. **Patient-file Verification:** Supported DICOM identity, geometry, reference and pixel checks.
2. **🤖 Dynamic Agent Copilot:** Optional Gemini function calling; offline mode performs intake only.
3. **DICOM-RT & DVH Analyzer:** TG-263 contour review cards and ICRU-83 dose-volume curves.
4. **Gamma Index QA:** AAPM TG-218 independent dose comparison (3% / 2 mm).
5. **TOPAS Monte Carlo Deck Generator:** Water-phantom and slab input templates; simulation is not run.
6. **Radiobiology (TCP / NTCP):** Conditional estimates from supplied DVHs and model parameters.
7. **Model Evaluation & Triage:** Supplied-array research assessment; does not run model inference.
8. **Interactive Agent Query:** Deterministic routing of supported explicit DVH/TOPAS requests.
9. **Stateful Python REPL Sandbox:** Trusted local Python; not a security sandbox.

### 4. CLI Execution
```bash
# Verify case intake
python agent_main.py verify-case --root data/demo/01_clean_case --case-id judge-demo-001

# Compute DVH metrics with TG-263 naming
python agent_main.py dvh \
  --rtdose data/demo/01_clean_case/synthetic_dose.dcm \
  --rtstruct data/demo/01_clean_case/synthetic_struct.dcm \
  --rtplan data/demo/01_clean_case/synthetic_plan.dcm \
  --roi Brainstem --roi PTV

# Generate 150 MeV proton TOPAS deck
python agent_main.py topas --particle proton --energy-mev 150 --histories 100000
```

### 5. Python API Usage
```python
from src.agent_dynamic import run_dynamic_agent

# Dynamic Copilot with grounded function calling
result = run_dynamic_agent(
    "Verify intake for selected_case.", case_directory="/authorized/local/case"
)

print("Disposition:", result.disposition)
print("Trajectory Steps:", len(result.trajectory))
print("Research Assessment:\n", result.response)
```

---

## 6. Data Safety & Physics Guardrails

1. **Source preservation:** Application output-path checks protect raw inputs and separate artifacts from source cases. Use read-only filesystem/container mounts for enforcement when running trusted Python; application checks are not an operating-system sandbox. Runtime outputs belong in separate processed/session storage.
2. **Absorbed Dose Non-Negativity:** Absorbed dose must satisfy $D(\vec{r}) \ge 0.0\text{ Gy}$ everywhere. Negative values immediately abort evaluation.
3. **Beam Kinetic Energy Bounds:** The template generator's supported application range is $0.01\text{ MeV} \le E \le 250\text{ MeV}$; this is not a universal bound for all radiation beams.
4. **Organ constraints:** Supply an institutionally reviewed protocol with prescription, fractionation and endpoint definitions. Copilot results remain research observations requiring review.
5. **Analysis privacy:** The canonical DVH boundary validates identity before building minimal in-memory analysis copies with substituted identifiers. It is not a general DICOM de-identification exporter; original files remain local and unchanged.

### Copilot execution contract

Gemini uses the official HTTPS generateContent API via Python's standard library; no additional GenAI package is needed. Set credentials only in process memory or enter them in the password field. Do not put credentials in files or queries. Hosted queries must be de-identified; local case paths and independent Gamma files belong in the separate local context fields. Opaque case handles and bounded tool summaries are sent to Google; raw DICOM files are not sent.

Execution is bounded to six rounds and twelve tool calls. Intake must be ready before DVH; ambiguous courses, missing ROIs, unknown arguments and provider failures remain explicit. Parallel function calls receive batched responses. Model prose cannot approve a case or substitute measurements. Offline mode performs local intake only. TOPAS output is a generated template, not a verified transport simulation. Strict 2%/2mm bands are research policy, not a universal TG-218 prescription.

Latest stress evidence: [full-corpus and copilot assessment](validation/evidence/stress/2026-10-21/README.md). Includes explicit provider failures, unresolved source findings and scope limitations.

## Safe research operation

See [hardening and operating instructions](docs/HARDENING.md) for input budgets, deterministic REST/provider distinctions, strict benchmark completeness, numerical threshold policy and deployment release gates. Only a single trusted operator research profile is implemented. Production and clinical readiness remain false.

## Ready-to-use synthetic demonstration

Use the [bundled synthetic DICOM-RT showcase](data/demo/README.md) for clean intake, DVH curves and deliberately faulty exports. It is artificial teaching data; verification outputs and previews are kept in the [separate showcase evidence folder](validation/evidence/showcase/README.md).
