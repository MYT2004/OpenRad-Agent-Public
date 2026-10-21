---
name: radiation_physics_dosimetry
description: Modular domain skill bundle for radiation transport, clinical dosimetry, DICOM-RT parsing, DVH evaluation, and TOPAS/Geant4 Monte Carlo simulation deck validation.
---

# Radiation Physics & Dosimetry Domain Playbook

This skill defines domain-specific physical rules, mathematical formulas, and unit guardrails for radiation transport and medical physics calculations.

---

## 1. Fundamental Physical Constants & Constraints

| Domain Parameter | Standard Units / Range | Guardrail Enforcement Rule |
| :--- | :--- | :--- |
| **Absorbed Dose** | Gray ($\text{Gy}$) or centiGray ($\text{cGy}$) | $D(\vec{r}) \ge 0$. Reject negative voxels caused by uncalibrated CT offset. |
| **Beam Kinetic Energy** | $0.01 \text{ MeV} \le E \le 250 \text{ MeV}$ | Enforce clinical bounds for photons ($MV$), electrons ($MeV$), and protons ($MeV$). |
| **Gamma Evaluation** | $3\% / 3\text{ mm}$, $10\%$ threshold | Calculate passing rate as percent of voxels where $\gamma(\vec{r}) \le 1.0$. |
| **Grid Orientation** | Unit direction vectors | Verify image coordinate axes satisfy orthogonality ($\mathbf{e}_x \cdot \mathbf{e}_y = 0$). |

---

## 2. Mathematical Definitions

### Dose-Volume Metrics
* **$D_{95\%}$**: Minimum absorbed dose delivered to at least $95\%$ of the specified ROI volume:
  $$D_{95\%} = \text{Dose at } V = 95\% \text{ on cumulative DVH}$$
* **$V_{50\%}$**: Percentage of total ROI volume receiving at least $50\%$ of the prescribed dose.
* **Equivalent Uniform Dose (EUD)**:
  $$\text{EUD} = \left( \sum_{i} v_i D_i^a \right)^{\frac{1}{a}}$$
  where $v_i$ is fractional voxel volume and $a$ is the tissue-specific parameter.

### Gamma Index Criteria
The $3\text{D}$ gamma index $\gamma(\vec{r}_m)$ evaluates spatial and dose agreement between evaluated dose $D_e$ and reference dose $D_r$:
$$\gamma(\vec{r}_m) = \min_{\vec{r}_r} \sqrt{ \left(\frac{\vert{}\vec{r}_e - \vec{r}_r\vert{}}{\delta r}\right)^2 + \left(\frac{D_e(\vec{r}_e) - D_r(\vec{r}_r)}{\delta D}\right)^2 }$$
* Default distance tolerance $\delta r = 3.0 \text{ mm}$
* Default dose tolerance $\delta D = 0.03 \times D_{\text{ref}}$

---

## 3. Physics Validation Check List

Prior to finalizing any output:
1. Verify that array dimensions match DICOM header metadata (`Rows`, `Columns`, `NumberOfFrames`).
2. Confirm mass-energy conservation in simulated target phantom geometries.
3. Check that generated TOPAS input decks contain required components: `Ge/World`, `Physics`, `BeamPosition`, and `Scorer`.
