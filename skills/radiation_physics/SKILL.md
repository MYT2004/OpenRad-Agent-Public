---
name: radiation-physics
description: >-
  Radiation physics workflow rules, domain mathematical formulations, KaTeX-compliant
  dosimetric equations, and clinical guardrails for the OpenRad framework.
---

# Radiation Physics Workflow Rules & Mathematical Formulations

This skill defines domain-specific physical rules, mathematical formulas, unit guardrails, and executable procedures for radiation transport and medical physics calculations using the `openrad` framework.

---

## 1. Fundamental Physical Constants & Guardrails

| Domain Parameter | Standard Units / Range | Guardrail Enforcement Rule | Action on Violation |
| :--- | :--- | :--- | :--- |
| **Absorbed Dose** | Gray ($\text{Gy}$) | $D(\vec{r}) \ge 0\text{ Gy}$. Negative dose values are physically invalid. | Reject output; prompt agent to re-check array calibration or background subtraction. |
| **Beam Energy** | $0.01\text{ MeV} \le E \le 250\text{ MeV}$ | Enforce clinical bounds for photons ($\text{MV}$), electrons ($\text{MeV}$), and protons ($\text{MeV}$). | Abort Monte Carlo execution; inform agent of unphysical energy parameter. |
| **Gamma Index** | $3\% / 2\text{ mm}$, $10\%$ cutoff | $0\% \le \text{Passing Rate} \le 100\%$. Voxels where $\gamma(\vec{r}) \le 1.0$ pass. | Check array alignment, origin shifts, and spatial registration dimensions. |
| **DICOM Geometry** | Millimeters ($\text{mm}$) | $\Delta x, \Delta y, \Delta z > 0$ and slice orientation vectors are orthogonal. | Flag DICOM header discrepancy. |
| **Radiobiology** | Probability $[0.0, 1.0]$ | $0.0 \le \text{NTCP}, \text{TCP} \le 1.0$, $TD_{50} > 0$, $m > 0$, $n > 0$. | Reject parameter set; flag biologically invalid exponent or normalizer. |

---

## 2. Mathematical Definitions & Clinical Criteria

### Dose-Volume Metrics (ICRU 83)

* **$D_{95\%}$**: Minimum absorbed dose delivered to at least $95\%$ of the target volume (surrogate for minimum target dose).
* **$D_{50\%}$**: Median absorbed dose delivered to the volume.
* **$D_{2\%}$**: Near-maximum absorbed dose delivered to $2\%$ of the volume.
* **$V_{50\text{Gy}}$**: Volume receiving at least $50\text{ Gy}$ (or $V_{50\%}$ percentage of prescribed dose).
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

## 3. Radiation Physics Workflow Rules

- Every tool must pass the `@post_tool_call` checks in `src.hooks`.
- Require finite nonnegative doses and array dimensions consistent with physical axes.
- Require finite beam energy from $0.01\text{ MeV}$ through $250\text{ MeV}$ and positive integer histories; these are application bounds.
- Prefer TG-263 primary ROI names and explicit DVH units ($D_{95\%}\text{[Gy]}$, $V_{50\text{Gy}}\text{[\%]}$). Legacy identities require reviewed mappings or built-in aliases (`BUILTIN_ROI_ALIASES`); laterality is never inferred.
- Use scrubbed in-memory analysis copies; never export original patient identifiers or write into `data/raw/`.
- Direct normal application derivatives to `data/processed/{patient_id}/` or isolated runtime session storage. Benchmark evidence belongs under ignored `validation/runs/<suite>/<run-id>/`; only reviewed public evidence snapshots belong under `validation/evidence/`. Never write derivatives into raw sources.
- Preserve frame and course-reference mismatches as blockers. An omitted RTPLAN leaves course linkage unverified.
- Use session artifact directories. The CPU filesystem is ephemeral on Cloud Run; durable storage requires a separately configured service.
- Sampling restrictions, uncertainty, and clinical release limits in `validation/audits/medical_physics.md` remain applicable.
