---
name: radiation_physics_dosimetry
description: Specialized domain skill for radiation physics, DICOM-RT parsing, DVH evaluation, and Monte Carlo input generation.
---

# Radiation Physics & Dosimetry Protocol

When processing radiation therapy, medical physics, or dosimetry tasks, follow this protocol:

## 1. Physical Units & Constraints
- **Dose Unit:** Always express absorbed dose in Gray (Gy) or centiGray (cGy).
- **Physical Boundaries:** Absorbed dose must be strictly non-negative ($D(\vec{r}) \ge 0$).
- **Energy Bounds:** Clinical radiotherapy photon/electron energies must fall within $0.01 \text{ MeV} \le E \le 250 \text{ MeV}$.

## 2. DICOM-RT & DVH Analysis
- Parse DICOM-RTSTRUCT and RTDOSE headers using `pydicom` / `PyMedPhys`.
- Always compute key clinical metrics: $D_{95\%}$, $D_{50\%}$, $D_{2\%}$, $V_{50\%}$, and Mean Dose ($\bar{D}$).
- Calculate $D_{95\%}$ using the formula:
  $$D_{95\%} = \text{Dose delivered to at least } 95\% \text{ of the target volume.}$$

## 3. Gamma Index Evaluation
- Default criteria: $3\% / 3\text{ mm}$ with a $10\%$ low-dose threshold unless specified otherwise.
- Output passing rates as a percentage ($\%$ of voxels with $\gamma \le 1.0$).

## 4. Deliverable Artifacts
- Save generated scripts to `./output/scripts/`.
- Save dose-volume histogram plots to `./output/plots/dvh_analysis.png`.
- Produce a structured markdown summary report upon completion.
