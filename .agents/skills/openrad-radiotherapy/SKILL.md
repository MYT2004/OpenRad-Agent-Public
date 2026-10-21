---
name: openrad-radiotherapy
description: >-
  Autonomous medical physics and radiotherapy intelligence. Use this skill when asked to
  analyze DICOM-RT (RTSTRUCT, RTDOSE), compute Dose Volume Histograms (DVH), evaluate
  AAPM TG-218 Gamma Index QA passing rates, generate TOPAS/Geant4 Monte Carlo parameter decks,
  model LKB NTCP or Poisson TCP radiobiology, or execute code in the stateful physics REPL.
---

# OpenRad Radiotherapy & Medical Physics Skill

This skill extends Antigravity with specialized radiation oncology and medical physics capabilities using the `openrad` library.

## Quick Reference Workflows

### 1. DVH Analysis (ICRU 83 Plan Quality)
To analyze structure doses from DICOM RTSTRUCT and RTDOSE:
```python
from openrad.tools.dicom_tool import analyze_dvh

results = analyze_dvh(
    dicom_rtstruct_path="data/raw/HNSCC-01-0199/10-26-2002-NA-RT SIMULATION-18560/1.000000-NA-59395/1-1.dcm",
    dicom_rtdose_path="data/raw/HNSCC-01-0199/10-26-2002-NA-RT SIMULATION-18560/1.000000-NA-67954/1-1.dcm",
    roi_names=["Cord", "Brainstem", "PTV 69.96 Gy"]
)
# Returns D95, D50, D2, V50, mean_dose_Gy, volume_cc, and dvh_curve points
```

### 2. Gamma Index QA (AAPM TG-218)
To compare reference TPS dose against measured or Monte Carlo dose:
```python
from openrad.tools.gamma_tool import evaluate_gamma_index

qa_results = evaluate_gamma_index(
    reference_dose_path=ref_dose_path_or_array,
    evaluated_dose_path=eval_dose_path_or_array,
    dose_tolerance_percent=3.0,
    distance_tolerance_mm=3.0,
    dose_threshold_percent=10.0
)
# Returns passing_rate (%), average_gamma, max_gamma
```

### 3. TOPAS Monte Carlo Input Deck Generation
To generate syntactically valid TOPAS (Geant4-based) simulation files:
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
To calculate complication or tumor control probabilities from DVH curve points:
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

### 5. Stateful REPL & Visualization
Execute dynamic scripts while preserving variables and capturing matplotlib plots:
```python
from openrad.sandbox.repl import StatefulPythonREPL

repl = StatefulPythonREPL(artifact_dir="artifacts")
result = repl.execute("plt.plot([0, 10], [0, 50]); plt.title('Dose Profile')")
# result.artifacts will contain the saved plot path
```

## Physics Guardrails Verification
Always ensure outputs respect:
- $D(\vec{r}) \ge 0\text{ Gy}$
- $0.01\text{ MeV} \le E \le 250\text{ MeV}$
- $0\% \le \text{Gamma Pass Rate} \le 100\%$
- $0.0 \le \text{Probability} \le 1.0$
- Orthogonal DICOM orientation cosines
