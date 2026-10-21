# OpenRad-Agent

> **Autonomous AI Agent for Radiation Oncology & Medical Imaging Intelligence**  
> Developed for the Open Scientific Intelligence (OSI) Hackathon 2026.

[![Tests](https://img.shields.io/badge/tests-passing-brightgreen)](./tests)
[![Python](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](./pyproject.toml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](./LICENSE)

---

## 1. Project Overview

In radiation therapy, clinical and physics data spans complex DICOM imaging series (CT simulation scans, RT structure sets, RT dose grids), longitudinal clinical metadata (PDF reports, JSON/FHIR), and Monte Carlo radiation transport simulations. 

**OpenRad-Agent** is an autonomous medical physics and radiotherapy intelligence system powered by **Google Antigravity**. It unifies multimodal clinical ingestion, deterministic radiation oncology tools, stateful REPL computing, and an uncompromising **Physics Validation Engine** that enforces domain guardrails (AAPM TG-218, ICRU 83, and QUANTEC tolerances).

---

## 2. System Architecture

```text
                              +-----------------------+
                              |   User Query / Task   |
                              +-----------+-----------+
                                          |
                                          v
                          +---------------+---------------+
                          |    Orchestrator / Agent Core  |
                          |   (LLM Reasoning & Strategy)  |
                          +---------------+---------------+
                                          |
                 +------------------------+------------------------+
                 |                                                 |
                 v                                                 v
   +-------------+-------------+                     +-------------+-------------+
   |   Deterministic Tools     |                     |    Stateful Python REPL    |
   |  (Structured Schema API)  |                     |    (Dynamic Execution)     |
   +-------------+-------------+                     +-------------+-------------+
                 |                                                 |
                 +------------------------+------------------------+
                                          |
                                          v
                          +---------------+---------------+
                          |   Physics Validation Engine   |
                          | (Constraints & Boundary Check)|
                          +---------------+---------------+
                                          |
                                   [Pass / Fail?]
                                     /         \
                         (Pass)     /           \     (Fail: Self-Correction Loop)
                                   v             v
                       +-----------+---+   +-----+-------------------+
                       | Output /      |   | Return Error + Trajectory|
                       | Artifacts     |   | Back to Agent Core      |
                       +---------------+   +-------------------------+
```

### Core Subsystems
1. **Orchestrator Core**: Manages prompt state, task decomposition, tool routing, and the autonomous self-correction loop.
2. **Deterministic Tool Registry**: Fast, typed function interfaces wrapping key radiotherapy libraries (`pydicom`, `PyMedPhys`, `scipy`, `numpy`).
3. **Stateful Python REPL**: Isolated execution environment where the agent dynamically manipulates 3D dose distributions and automatically intercepts `matplotlib` figures as artifacts.
4. **Physics Validation Engine**: Hardcoded domain guardrails that prevent unphysical doses, invalid beam energies, or spatial misregistrations.

---

## 3. Structured Tool Definitions

| Tool Name | Module | Description | Input Schema |
| :--- | :--- | :--- | :--- |
| `analyze_dvh` | `openrad.tools.dicom_tool` | Parses DICOM RTSTRUCT & RTDOSE, samples 3D dose grids within polygonal contours, and calculates D95, D50, D2, V50, Dmean, Dmin, Dmax. | `DVHAnalysisInput` |
| `evaluate_gamma_index` | `openrad.tools.gamma_tool` | Computes 2D/3D Gamma Index passing rates, average gamma, and max gamma (AAPM TG-218 standard). | `GammaEvaluationInput` |
| `generate_topas_deck` | `openrad.tools.topas_tool` | Generates syntactically valid TOPAS (Geant4-based) parameter decks for proton, e-, gamma, and neutron radiation transport. | `TOPASGeneratorInput` |
| `calculate_tcp_ntcp` | `openrad.tools.radiobio_tool` | Calculates Lyman-Kutcher-Burman (LKB) NTCP, Poisson-LQ TCP, and Equivalent Uniform Dose (EUD). | `RadiobiologyInput` |
| `execute_python_repl` | `openrad.sandbox.repl` | Stateful execution sandbox capturing figures, logs, and inspecting dose arrays for physics violations. | `code: str` |
| `parse_dicom_metadata` | `openrad.tools.multimodal_readers` | Lightweight DICOM header parsing without loading heavy pixel arrays. | `file_path: str` |
| `parse_patient_pdf/json/csv` | `openrad.tools.multimodal_readers` | Multi-format clinical document and tabular metadata parsers. | `file_path: str` |

---

## 4. Physics Validation Guardrails

To enforce maximum clinical safety and reliability, code execution and tool calls pass through the **Physics Validation Engine** before producing outputs:

| Physics Domain | Rule Description | Action on Violation |
| :--- | :--- | :--- |
| **Dose Grid Integrity** | Dose values $D(\vec{r}) \ge 0\text{ Gy}$. Negative dose values are physically invalid. | Reject output; auto-prompt agent to re-check array calibration or background subtraction. |
| **Beam Energy Bounds** | Clinical radiotherapy energies restricted to $0.01\text{ MeV} \le E \le 250\text{ MeV}$. | Abort Monte Carlo execution; inform agent of unphysical energy parameter. |
| **Gamma Index** | $0\% \le \text{Pass Rate} \le 100\%$. | Check array alignment and spatial registration dimensions. |
| **DICOM Geometry** | Grid voxel spacing $\Delta x, \Delta y, \Delta z > 0$ and slice orientation vectors are orthogonal. | Flag DICOM header discrepancy. |
| **Radiobiology** | Normal tissue complication and tumor control probabilities $0.0 \le P \le 1.0$. | Reject parameter set; flag biologically invalid exponent or normalizer. |

---

## 5. Repository Structure

```text
OpenRad-Agent/
├── .agents/
│   ├── rules/
│   │   └── AGENTS.md                  # Domain physics rules & mandatory guardrails
│   └── skills/
│       └── openrad-radiotherapy/
│           └── SKILL.md               # Antigravity skill playbook & clinical SOPs
├── openrad/
│   ├── core/                          # Orchestrator agent & medical physics prompts
│   ├── tools/                         # Deterministic DVH, Gamma, TOPAS, & Radiobio tools
│   ├── sandbox/                       # Stateful Python REPL with plot artifact interception
│   ├── validation/                    # Physics Validation Engine & unit boundary checks
│   └── storage/                       # Session trajectory & artifact persistence manager
├── examples/                          # End-to-end DVH and TOPAS demonstration scripts
├── tests/                             # Pytest suite (16 tests verifying all guardrails & tools)
├── app.py                             # Streamlit interactive clinician dashboard
├── server.py                          # FastAPI REST & streaming gateway
├── Dockerfile                         # Container deployment for hackathon presentation
├── pyproject.toml                     # Python package build configuration
├── requirements.txt                   # Unified dependency specification
└── README.md                          # Architectural specification and guide
```

---

## 6. Quickstart & Installation

### 1. Setup Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Run the Verification Test Suite
```bash
pytest -v
```

### 3. Launch Interactive Streamlit Dashboard
```bash
streamlit run app.py
```

### 4. Launch FastAPI REST Gateway
```bash
uvicorn server.py:app --host 0.0.0.0 --port 8000
```

### 5. Run Standalone Demonstration Scripts
```bash
# DVH analysis & Radiobiological modeling on TCIA patient dataset
python examples/dvh_analysis_demo.py

# TOPAS Monte Carlo deck generation & physics guardrail self-correction
python examples/topas_generation_demo.py
```
