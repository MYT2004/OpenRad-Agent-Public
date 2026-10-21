# OpenRad Agent Workspace Rules & Physics Guardrails

These rules apply to all AI agents operating within the OpenRad Agent repository.

## 1. Domain Physics Guardrails (Mandatory Enforcement)
Every agent action, tool invocation, or Python code execution that generates or processes radiotherapy data MUST pass through the Physics Validation Engine (`openrad.validation.physics_rules.PhysicsValidationEngine`):

- **Dose Grid Integrity**:
  - Dose values $D(\vec{r}) \ge 0\text{ Gy}$ must be strictly non-negative.
  - If negative dose is produced, abort output and prompt for array recalibration, intercept rescaling, or background subtraction review.
- **Beam Energy Bounds**:
  - Clinical radiotherapy beam energies must fall within $0.01\text{ MeV} \le E \le 250\text{ MeV}$.
  - Abort Monte Carlo deck executions outside this range.
- **Gamma Index Boundaries**:
  - Passing rates must lie within $0\% \le \text{Pass Rate} \le 100\%$.
  - Values outside this range indicate severe grid misregistration or affine misalignment.
- **DICOM Spatial Geometry**:
  - Voxel dimensions $\Delta x, \Delta y, \Delta z > 0$ strictly positive.
  - Slice orientation cosines must be orthogonal unit vectors ($\vec{r} \cdot \vec{c} \approx 0$).

## 2. Radiotherapy Code Guidelines
- Use the typed deterministic tools in `openrad.tools` (`analyze_dvh`, `evaluate_gamma_index`, `generate_topas_deck`, `calculate_tcp_ntcp`).
- When running dynamic scripts, utilize `openrad.sandbox.repl.StatefulPythonREPL` to maintain persistent session state and capture matplotlib visualization artifacts.
- When a physics guardrail violation occurs, trigger the self-correction loop to diagnose the root cause and retry with valid parameters.
