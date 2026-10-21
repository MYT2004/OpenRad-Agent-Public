# OpenRad Agent

**OpenRad Agent** is an autonomous Medical Physics and Radiotherapy AI Agent built for rapid hackathon deployment, clinical plan evaluation, quality assurance (QA), Monte Carlo transport generation, and radiobiological modeling.

---

## 1. System Architecture

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
1. **Orchestrator (LLM Core)**: Manages prompt state, task decomposition, tool routing, and the autonomous self-correction loop.
2. **Deterministic Tool Registry**: Fast, typed function interfaces wrapping key radiotherapy libraries (`pydicom`, `PyMedPhys`, `scipy`, `numpy`).
3. **Stateful Python REPL**: Isolated environment preserving variable state where the agent can dynamically write scripts, transform 3D dose grids, and automatically capture visualization artifacts (`matplotlib`).
4. **Physics Validation Engine**: Hardcoded domain guardrails and boundary checks that validate outputs and trigger self-correction upon unphysical parameters.

---

## 2. Structured Tool Definitions

| Tool Name | Module | Description | Input Schema |
| :--- | :--- | :--- | :--- |
| `analyze_dvh` | `openrad.tools.dicom_tool` | Parses DICOM RTSTRUCT & RTDOSE, computes cumulative DVHs, and extracts D95, D50, D2, V50, Dmean, Dmin, Dmax. | `DVHAnalysisInput` |
| `evaluate_gamma_index` | `openrad.tools.gamma_tool` | Computes 2D/3D Gamma Index passing rates, average gamma, and max gamma (AAPM TG-218 standard). | `GammaEvaluationInput` |
| `generate_topas_deck` | `openrad.tools.topas_tool` | Generates syntactically valid TOPAS (Geant4-based) parameter decks for proton, e-, gamma, and neutron radiation transport. | `TOPASGeneratorInput` |
| `calculate_tcp_ntcp` | `openrad.tools.radiobio_tool` | Calculates Lyman-Kutcher-Burman (LKB) NTCP, Poisson-LQ TCP, and Equivalent Uniform Dose (EUD). | `RadiobiologyInput` |
| `execute_python_repl` | `openrad.sandbox.repl` | Stateful execution sandbox capturing figures, logs, and inspecting dose arrays for physics violations. | `code: str` |

---

## 3. Physics Validation Guardrails

To enforce clinical reliability, the output of code execution and tool calls passes through a validation layer before hitting the final output:

| Physics Domain | Rule Description | Action on Violation |
| :--- | :--- | :--- |
| **Dose Grid Integrity** | Dose values $D(\vec{r}) \ge 0\text{ Gy}$. Negative dose values are physically invalid. | Reject output; auto-prompt agent to re-check array calibration or background subtraction. |
| **Beam Energy Bounds** | Clinical radiotherapy energies restricted to $0.01\text{ MeV} \le E \le 250\text{ MeV}$. | Abort Monte Carlo execution; inform agent of unphysical energy parameter. |
| **Gamma Index** | $0\% \le \text{Pass Rate} \le 100\%$. | Check array alignment and spatial registration dimensions. |
| **DICOM Geometry** | Grid voxel spacing $\Delta x, \Delta y, \Delta z > 0$ and slice orientation vectors are orthogonal. | Flag DICOM header discrepancy. |
| **Radiobiology** | Normal tissue complication and tumor control probabilities $0.0 \le P \le 1.0$. | Reject parameter set; flag biologically invalid exponent or normalizer. |

---

## 4. Repository Structure

```text
openrad-agent/
├── README.md
├── pyproject.toml
├── requirements.txt
├── openrad/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── agent.py          # Main execution loop, intent routing & LLM orchestration
│   │   └── prompts.py        # Domain-specific system prompts
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── dicom_tool.py     # pydicom & DVH calculation wrappers
│   │   ├── gamma_tool.py     # PyMedPhys & cKDTree Gamma analysis
│   │   ├── radiobio_tool.py  # LKB TCP/NTCP calculation logic
│   │   └── topas_tool.py     # Monte Carlo TOPAS parameter deck builder
│   ├── sandbox/
│   │   ├── __init__.py
│   │   └── repl.py           # Stateful Python execution environment
│   └── validation/
│       ├── __init__.py
│       └── physics_rules.py  # Physics bounds and unit checks
├── examples/
│   ├── dvh_analysis_demo.py
│   └── topas_generation_demo.py
└── tests/
    └── test_physics_validation.py
```

---

## 5. Quickstart & Installation

### Setup Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Run the Test Suite
```bash
pytest -v
```

### Run the End-to-End Demos
```bash
# 1. DVH analysis & Radiobiological modeling on patient dataset
python examples/dvh_analysis_demo.py

# 2. TOPAS Monte Carlo deck generation & physics guardrail self-correction
python examples/topas_generation_demo.py
```

---

## 6. Example Usage via Python API

```python
from openrad.core.agent import OpenRadAgent

# Initialize agent
agent = OpenRadAgent()

# 1. Run a task through the orchestrator
result = agent.run("Calculate DVH metrics for Cord, Brainstem, and PTV 69.96 Gy")
print(result.response)

# 2. Generate a Monte Carlo deck with physics validation
result = agent.run("Generate TOPAS simulation deck for a 160 MeV proton beam in water phantom")
print(result.response)
print("Saved artifacts:", result.artifacts)
```
