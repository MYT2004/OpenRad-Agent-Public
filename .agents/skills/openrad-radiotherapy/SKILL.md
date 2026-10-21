---
name: openrad-radiotherapy
description: >-
  Autonomous medical physics and radiotherapy intelligence. Use this skill when asked to
  analyze DICOM-RT (RTSTRUCT, RTDOSE), compute Dose Volume Histograms (DVH), evaluate
  AAPM TG-218 Gamma Index QA passing rates, generate TOPAS/Geant4 Monte Carlo parameter decks,
  model LKB NTCP or Poisson TCP radiobiology, or execute code in the stateful physics REPL.
---

# OpenRad Radiotherapy & Radiation Physics Playbook

This skill defines domain-specific physical rules, mathematical formulas, unit guardrails, and executable procedures for radiation transport and medical physics calculations using the `openrad` framework.

---

## 1. Fundamental Physical Constants & Guardrails

| Domain Parameter | Standard Units / Range | Guardrail Enforcement Rule | Action on Violation |
| :--- | :--- | :--- | :--- |
| **Absorbed Dose** | Gray ($\text{Gy}$) | $D(\vec{r}) \ge 0\text{ Gy}$. Negative dose values are physically invalid. | Reject output; auto-prompt agent to re-check array calibration or background subtraction. |
| **Beam Energy** | $0.01\text{ MeV} \le E \le 250\text{ MeV}$ | Enforce clinical bounds for photons ($\text{MV}$), electrons ($\text{MeV}$), and protons ($\text{MeV}$). | Abort Monte Carlo execution; inform agent of unphysical energy parameter. |
| **Gamma Index** | $3\% / 2\text{ mm}$, $10\%$ cutoff | $0\% \le \text{Passing Rate} \le 100\%$. Voxels where $\gamma(\vec{r}) \le 1.0$ pass. | Check array alignment, origin shifts, and spatial registration dimensions. |
| **DICOM Geometry** | Millimeters ($\text{mm}$) | $\Delta x, \Delta y, \Delta z > 0$ and slice orientation vectors are orthogonal. | Flag DICOM header discrepancy. |
| **Radiobiology** | Probability $[0.0, 1.0]$ | $0.0 \le \text{NTCP}, \text{TCP} \le 1.0$, $TD_{50} > 0$, $m > 0$, $n > 0$. | Reject parameter set; flag biologically invalid exponent or normalizer. |

---

## 2. Mathematical Definitions & Clinical Criteria

### Dose-Volume Metrics (ICRU 83)
* **$D_{95\%}$**: Minimum absorbed dose delivered to at least 95% of the target volume (surrogate for minimum target dose).
* **$D_{50\%}$**: Median absorbed dose delivered to the volume.
* **$D_{2\%}$**: Near-maximum absorbed dose delivered to 2% of the volume.
* **$V_{50\text{Gy}}$**: Volume receiving at least 50 Gy (or $V_{50\%}$ percentage of prescribed dose).
* **Equivalent Uniform Dose (gEUD)**:

$$
\text{gEUD} = \left( \sum_{i} v_i D_i^{1/n} \right)^n
$$

where $v_i$ is the fractional voxel volume, $D_i$ is voxel dose, and $n$ is the organ-specific volume effect parameter.

### Lyman-Kutcher-Burman (LKB) NTCP Model

$$
t = \frac{\text{gEUD} - TD_{50}}{m \cdot TD_{50}}
$$

$$
\text{NTCP} = \frac{1}{\sqrt{2\pi}} \int_{-\infty}^t e^{-u^2/2} du = \frac{1}{2} \left[ 1 + \text{erf}\left( \frac{t}{\sqrt{2}} \right) \right]
$$

### Gamma Index Criteria (AAPM TG-218)

$$
\Gamma(\vec{r}_e, \vec{r}_r) = \sqrt{ \left(\frac{\|\vec{r}_e - \vec{r}_r\|}{\delta r}\right)^2 + \left(\frac{D_e(\vec{r}_e) - D_r(\vec{r}_r)}{\delta D}\right)^2 }
$$

$$
\gamma(\vec{r}_e) = \min_{\vec{r}_r} \Gamma(\vec{r}_e, \vec{r}_r)
$$

Passing rate is the percentage of evaluated voxels (above low-dose threshold $10\% \times D_{\max}$) satisfying $\gamma \le 1.0$.

---

## 3. Quick Reference Python Workflows

### 1. DVH Analysis (ICRU 83 Plan Quality)
```python
from openrad.tools.dicom_tool import analyze_dvh

results = analyze_dvh(
    dicom_rtstruct_path="data/raw/HNSCC-01-0199/10-26-2002-NA-RT SIMULATION-18560/1.000000-NA-59395/1-1.dcm",
    dicom_rtdose_path="data/raw/HNSCC-01-0199/10-26-2002-NA-RT SIMULATION-18560/1.000000-NA-67954/1-1.dcm",
    roi_names=["Cord", "Brainstem", "PTV 69.96 Gy"]
)
```

### 2. Gamma Index QA (AAPM TG-218)
```python
from openrad.tools.gamma_tool import evaluate_gamma_index

qa_results = evaluate_gamma_index(
    reference_dose_path=ref_dose_path,
    evaluated_dose_path=eval_dose_path,
    dose_tolerance_percent=3.0,
    distance_tolerance_mm=2.0,
    dose_threshold_percent=10.0
)
```

### 3. TOPAS Monte Carlo Input Deck Generation
```python
from openrad.tools.topas_tool import generate_topas_deck

deck = generate_topas_deck(
    particle_type="proton",  # 'proton', 'e-', 'gamma', 'neutron'
    energy_MeV=150.0,
    geometry_type="water_phantom",  # 'water_phantom', 'slab_heterogeneity', 'ct_patient'
    phantom_dimensions_cm=[30.0, 30.0, 30.0],
    number_of_histories=100000
)
```

### 4. Radiobiological Modeling (LKB NTCP & Poisson TCP)
```python
from openrad.tools.radiobio_tool import calculate_tcp_ntcp

# LKB NTCP
ntcp_res = calculate_tcp_ntcp(
    dvh_data=cord_dvh_curve,
    model_type="LKB",
    parameters={"TD50": 65.0, "m": 0.175, "n": 0.05}
)

# Poisson TCP
tcp_res = calculate_tcp_ntcp(
    dvh_data=ptv_dvh_curve,
    model_type="Poisson_LQ",
    parameters={"TCD50": 65.0, "gamma_50": 2.5}
)
```

### 5. Stateful REPL & Plot Interception
```python
from openrad.sandbox.repl import StatefulPythonREPL

repl = StatefulPythonREPL(artifact_dir="artifacts")
result = repl.execute("plt.plot([0, 10], [0, 50]); plt.title('Dose Profile')")
# result.artifacts contains saved figure paths
```

## TG-263 nomenclature

Use `openrad.validation.nomenclature` and the pinned AAPM 20170815 vocabulary. Primary names are preferred. Preserve source ROI names, laterality and qualifiers. Unknown or reverse-order names require review; pass human-reviewed aliases via `reviewed_name_map`. Reject duplicate case-insensitive names and mapping collisions. Report the supported syntax scope; never claim naming confirms anatomy. DVH results expose `tg263_metrics` with explicit labels such as `D95%[Gy]` and `V50Gy[%]`. See `docs/TG263.md` for source provenance and unsupported target forms. Never change patient data or requested beam parameters to make a guardrail pass.
