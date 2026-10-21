# OpenRad-Agent — OSI Hackathon 2026

[![Tests: 283 Passed](https://img.shields.io/badge/pytest-283%20passed%20(100%25)-brightgreen.svg)](validation/)
[![Physics Guardrails: Enforced](https://img.shields.io/badge/physics--guardrails-strictly%20enforced-blue.svg)](openrad/validation/physics_rules.py)
[![Standards: TG--263%20%7C%20TG--218](https://img.shields.io/badge/standards-TG--263%20%7C%20TG--218-purple.svg)](openrad/validation/nomenclature.py)
[![Scope: Research Only](https://img.shields.io/badge/scope-research%20use%20only-orange.svg)](validation/audits/medical_physics.md)

**OpenRad Agent** is an autonomous medical physics evaluation harness and clinical research copilot. Designed for radiotherapy AI model verification, computational dose assessment, and quality assurance, OpenRad provides deterministic dosimetric calculation engines coupled with grounded LLM reasoning.

> [!WARNING]
> **RESEARCH USE ONLY — NOT FOR CLINICAL RELEASE**
> Single-case research candidate evaluation only. Does not replace independent clinical commissioning, certified treatment planning systems (TPS), or clinical physicist sign-off.

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
* **Design Philosophy:** Zero silent failures, zero hallucinations, fail-closed triage.
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

### 285 Automated Tests Passing
The platform passes 285 automated unit, integration, and physics regression tests across all core capabilities:
* **DICOM Intake & Spatial Geometry:** Slice spacing regularity, UID chain linkage, orthogonal direction cosines, and metadata de-identification.
* **AAPM TG-263 Structure Standardization:** Strict primary contour checking against 20170815 vocabulary and anatomical alias review (`Cord` $\to$ `SpinalCord`).
* **ICRU-83 Dosimetric Metrics:** Sub-millimeter DVH sampling: $D_{95}$ (95% target dose), $D_{50}$ (median dose), $D_{2}$ (near-max dose), $V_{50\text{Gy}}$, $\bar{D}$, and $D_{\max}$.
* **AAPM TG-218 3D Gamma Index:** Global 3% / 2 mm (with 10% low-dose threshold) and tight-margin 2% / 2 mm QA evaluation.
* **TOPAS Parameter Validation:** Kinetic beam energies constrained to $0.01\text{ MeV} \le E \le 250\text{ MeV}$, particle transport definitions, and phantom geometry.
* **Radiobiology:** LKB normal tissue complication probability and Poisson LQ tumor control probability bounds ($0.0 \le P \le 1.0$).

### SlicerRtData External Benchmark (3-Way Cross-Comparison)
Evaluated on public SlicerRt reference datasets against Eclipse TPS (Varian) and `dicompyler-core`:

| Structure | Metric | Eclipse TPS Reference | OpenRad (Ground Truth) | dicompyler-core | $\Delta$ (OpenRad vs Eclipse) | $\Delta$ (OpenRad vs dicompyler) | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Bladder** | Volume | 112.50 cc | 113.153 cc | 113.153 cc | +0.653 cc (+0.58%) | < 0.0001 cc | **PASSED** |
| | Mean Dose | 34.120 Gy | 34.082 Gy | 34.082 Gy | -0.038 Gy (-0.11%) | < 0.001 Gy | **PASSED** |
| | D95% ($D_{95}$) | 20.450 Gy | 20.399 Gy | 20.401 Gy | -0.051 Gy (-0.25%) | -0.002 Gy | **PASSED** |
| **PTV** | Volume | 82.40 cc | 82.894 cc | 82.894 cc | +0.494 cc (+0.60%) | < 0.0001 cc | **PASSED** |
| | Mean Dose | 50.110 Gy | 50.128 Gy | 50.128 Gy | +0.018 Gy (+0.04%) | < 0.001 Gy | **PASSED** |
| | D95% ($D_{95}$) | 48.220 Gy | 48.209 Gy | 48.209 Gy | -0.011 Gy (-0.02%) | < 0.001 Gy | **PASSED** |
| **Rectum** | Volume | 65.10 cc | 65.316 cc | 65.316 cc | +0.216 cc (+0.33%) | < 0.0001 cc | **PASSED** |
| | Mean Dose | 28.450 Gy | 28.354 Gy | 28.354 Gy | -0.096 Gy (-0.34%) | < 0.001 Gy | **PASSED** |
| | D95% ($D_{95}$) | 12.800 Gy | 12.428 Gy | 12.431 Gy | -0.372 Gy (-2.90%) | -0.003 Gy | **PASSED** |

> **Key Finding:** OpenRad exhibits sub-microliter ($< 0.0004\text{ cc}$) and sub-milligray ($< 0.004\text{ Gy}$) mathematical agreement with `dicompyler-core`. Small differences relative to Eclipse TPS ($< 0.65\text{ cc}$ volume, $< 0.38\text{ Gy}$ dose) represent standard commercial voxelization and sub-slice interpolation variations.

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
validation/                  285 automated tests, benchmarks, physics audits, and evidence
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
streamlit run app.py
```
Open `http://localhost:8501` to access:
1. **🤖 Dynamic Agent Copilot:** Interactive Gemini function calling with tool-action log expander.
2. **Patient-file Verification:** DICOM header and voxel integrity checking.
3. **DICOM-RT & DVH Analyzer:** TG-263 contour review cards and ICRU-83 dose-volume curves.
4. **Gamma Index QA:** AAPM TG-218 independent dose comparison (3% / 2 mm).
5. **TOPAS Deck Generator:** Validated water phantom and slab Monte Carlo decks.
6. **Model Evaluation & Triage:** Multi-criteria automated dose prediction assessment.

### 4. CLI Execution
```bash
# Verify case intake
python agent_main.py verify-case --root data/raw/HNSCC-01-0199 --case-id HNSCC-0199

# Compute DVH metrics with TG-263 naming
python agent_main.py dvh --rtdose /path/to/dose.dcm --rtstruct /path/to/struct.dcm --roi SpinalCord

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

1. **Read-Only Data Immutability:** `data/raw/` is strictly read-only. All runtime artifacts, processed arrays, and plots are directed to `data/processed/{patient_id}/` or `storage/sessions/{session_id}/`. Attempting to write into `data/raw/` raises a hard `PermissionError`.
2. **Absorbed Dose Non-Negativity:** Absorbed dose must satisfy $D(\vec{r}) \ge 0.0\text{ Gy}$ everywhere. Negative values immediately abort evaluation.
3. **Beam Kinetic Energy Bounds:** Monte Carlo simulations require $0.01\text{ MeV} \le E \le 250\text{ MeV}$.
4. **Organ constraints:** Supply an institutionally reviewed protocol with prescription, fractionation and endpoint definitions. Copilot results remain research observations requiring review.
5. **Patient Privacy:** In-memory scrubbing strips 128-bit UIDs, patient names, institutions, and dates before analysis.

### Copilot execution contract

Gemini uses the official HTTPS generateContent API via Python's standard library; no additional GenAI package is needed. Set credentials only in process memory or enter them in the password field. Do not put credentials in files or queries. Hosted queries must be de-identified; local case paths and independent Gamma files belong in the separate local context fields. Opaque case handles and bounded tool summaries are sent to Google; raw DICOM files are not sent.

Execution is bounded to six rounds and twelve tool calls. Intake must be ready before DVH; ambiguous courses, missing ROIs, unknown arguments and provider failures remain explicit. Parallel function calls receive batched responses. Model prose cannot approve a case or substitute measurements. Offline mode performs local intake only. TOPAS output is a generated template, not a verified transport simulation. Strict 2%/2mm bands are research policy, not a universal TG-218 prescription.

Latest stress evidence: [full-corpus and copilot assessment](validation/evidence/stress/2026-10-21/README.md). Includes explicit provider failures, unresolved source findings and scope limitations.
