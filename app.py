"""Streamlit Interactive Application for OpenRad Agent."""

import os
import json
import streamlit as st
import matplotlib.pyplot as plt
import numpy as np

from openrad.core.agent import OpenRadAgent
from openrad.tools.dicom_tool import analyze_dvh
from openrad.tools.gamma_tool import evaluate_gamma_index
from openrad.tools.radiobio_tool import calculate_tcp_ntcp
from openrad.tools.topas_tool import generate_topas_deck
from openrad.validation.physics_rules import PhysicsValidationEngine, BeamEnergyBoundsError

st.set_page_config(page_title="OpenRad Agent | Autonomous Medical Physics AI", layout="wide")

st.title("🏥 OpenRad Agent")
st.warning("Research prototype: clinical validation and uncertainty margins are not established.")
st.markdown("**Autonomous Medical Physics & Radiotherapy Intelligence Agent**")

# Sidebar Controls
st.sidebar.header("Agent Control Panel")
agent_mode = st.sidebar.selectbox(
    "Select Workflow",
    [
        "Interactive Agent Query",
        "DICOM-RT & DVH Analyzer",
        "Gamma Index QA (AAPM TG-218)",
        "TOPAS Monte Carlo Deck Generator",
        "Radiobiology (TCP / NTCP)",
        "Stateful Python REPL Sandbox",
    ],
)

# Patient Data Directory
SAMPLE_STRUCT = "data/raw/HNSCC-01-0199/10-26-2002-NA-RT SIMULATION-18560/1.000000-NA-59395/1-1.dcm"
SAMPLE_DOSE = "data/raw/HNSCC-01-0199/10-26-2002-NA-RT SIMULATION-18560/1.000000-NA-67954/1-1.dcm"

if "agent" not in st.session_state:
    st.session_state.agent = OpenRadAgent()

# -----------------------------------------------------------------------------
# Mode 1: Interactive Agent Query
# -----------------------------------------------------------------------------
if agent_mode == "Interactive Agent Query":
    st.subheader("Autonomous Orchestration & Tool Routing")
    st.info("Ask the agent clinical tasks, DVH queries, or Monte Carlo setups. Guardrails will validate output automatically.")

    user_query = st.text_input(
        "Enter clinical radiotherapy task:",
        value="Calculate DVH metrics for Cord, Brainstem, and PTV 69.96 Gy",
    )

    if st.button("Execute Task"):
        with st.spinner("Agent orchestrating tools and validating physics guardrails..."):
            result = st.session_state.agent.run(user_query)

            st.markdown(result.response)

            if result.tool_records:
                st.subheader("Subsystem Execution Trajectory")
                for rec in result.tool_records:
                    status_badge = "✅ Passed" if rec.physics_passed else "❌ Guardrail Violation"
                    with st.expander(f"Tool: `{rec.tool_name}` - Physics: {status_badge}"):
                        st.write("**Arguments:**", rec.arguments)
                        if rec.error:
                            st.error(rec.error)
                        if rec.output:
                            st.json(rec.output if isinstance(rec.output, dict) else str(rec.output)[:500])

            if result.artifacts:
                st.subheader("Generated Artifacts")
                for art in result.artifacts:
                    if art.endswith(".png"):
                        st.image(art)
                    elif art.endswith(".txt"):
                        with open(art, "r") as f:
                            st.code(f.read()[:1000], language="bash")

# -----------------------------------------------------------------------------
# Mode 2: DICOM-RT & DVH Analyzer
# -----------------------------------------------------------------------------
elif agent_mode == "DICOM-RT & DVH Analyzer":
    st.subheader("Dose Volume Histogram (DVH) Analyzer (ICRU 83)")

    col1, col2 = st.columns(2)
    with col1:
        struct_file = st.text_input("RTSTRUCT Path:", value=SAMPLE_STRUCT)
    with col2:
        dose_file = st.text_input("RTDOSE Path:", value=SAMPLE_DOSE)

    roi_text = st.text_area("Exact ROI names (one per line; TG-263 primary names preferred)", value="SpinalCord\nBrainstem\nPTV_High")
    rois = [name for name in roi_text.splitlines() if name]
    mapping_text = st.text_area("Human-reviewed legacy ROI mapping (JSON)", value="{}", help='Example after anatomical review: {"Cord": "SpinalCord"}. No automatic renaming occurs.')

    if st.button("Compute DVH"):
        if os.path.exists(struct_file) and os.path.exists(dose_file):
            with st.spinner("Extracting contours, sampling 3D dose grid, and calculating DVH..."):
                try:
                    if not rois:
                        raise ValueError("Select at least one ROI.")
                    reviewed_map = json.loads(mapping_text)
                    if not isinstance(reviewed_map, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in reviewed_map.items()):
                        raise ValueError("Mapping must be a JSON object of source and canonical name strings.")
                    dvh_res = analyze_dvh(struct_file, dose_file, rois, reviewed_name_map=reviewed_map)
                except (ValueError, AttributeError) as exc:
                    st.error(str(exc))
                    st.stop()
                st.json(dvh_res["nomenclature"])
                for name, entry in dvh_res["structures"].items():
                    if not entry.get("found"):
                        st.error(f"{name}: {entry['error']}")
                st.success(f"Processed 3D dose grid {dvh_res['dose_grid_shape']} | Max Dose: {dvh_res['max_dose_Gy']:.2f} Gy")

                fig, ax = plt.subplots(figsize=(8, 5))
                cols = st.columns(len(rois))

                for idx, (r_name, s_data) in enumerate(dvh_res["structures"].items()):
                    if s_data.get("found"):
                        with cols[idx % len(cols)]:
                            st.metric(f"{r_name} D95%[Gy]", f"{s_data.get('D95_Gy')} Gy")
                            st.write(f"Volume: `{s_data.get('volume_cc')} cc`")
                            st.write(f"Dmean: `{s_data.get('mean_dose_Gy')} Gy`")
                            st.write(f"V50Gy[%]: `{s_data.get('V50_percent')}%`")

                        curve = s_data.get("dvh_curve")
                        if curve:
                            ax.plot(curve["dose_bins_Gy"], curve["volume_percent"], label=r_name, lw=2.2)

                ax.set_title("Dose Volume Histogram", fontsize=12, fontweight="bold")
                ax.set_xlabel("Dose (Gy)")
                ax.set_ylabel("Volume (%)")
                ax.grid(True, linestyle="--", alpha=0.5)
                ax.legend()
                ax.set_xlim(0, max(dvh_res["max_dose_Gy"] * 1.05, 80))
                ax.set_ylim(0, 105)
                st.pyplot(fig)
        else:
            st.error("DICOM files not found at specified paths.")

# -----------------------------------------------------------------------------
# Mode 3: Gamma Index QA
# -----------------------------------------------------------------------------
elif agent_mode == "Gamma Index QA (AAPM TG-218)":
    st.subheader("Gamma Index QA Evaluation")
    c1, c2, c3 = st.columns(3)
    with c1:
        d_tol = st.number_input("Dose Tolerance (%)", value=3.0)
    with c2:
        dist_tol = st.number_input("Distance Tolerance (mm)", value=2.0)
    with c3:
        cut_tol = st.number_input("Low-dose Cutoff (%)", value=10.0)

    if st.button("Evaluate Gamma Index"):
        with st.spinner("Computing spatial distance-to-agreement and dose differences..."):
            gamma_res = evaluate_gamma_index(
                SAMPLE_DOSE,
                SAMPLE_DOSE,
                dose_tolerance_percent=d_tol,
                distance_tolerance_mm=dist_tol,
                dose_threshold_percent=cut_tol,
            )
            st.metric("Gamma Passing Rate", f"{gamma_res['passing_rate']}%")
            st.write(f"Average Gamma: `{gamma_res['average_gamma']}` | Max Gamma: `{gamma_res['max_gamma']}`")
            st.write(f"Evaluated Voxels: `{gamma_res['evaluated_voxels']}` / `{gamma_res['total_voxels']}`")

# -----------------------------------------------------------------------------
# Mode 4: TOPAS Monte Carlo Deck Generator
# -----------------------------------------------------------------------------
elif agent_mode == "TOPAS Monte Carlo Deck Generator":
    st.subheader("TOPAS / Geant4 Parameter Deck Generator")
    c1, c2 = st.columns(2)
    with c1:
        particle = st.selectbox("Particle Type", ["proton", "e-", "gamma", "neutron"])
        energy = st.number_input("Beam Energy (MeV)", value=150.0, min_value=0.0, max_value=1000.0)
    with c2:
        geom = st.selectbox("Geometry", ["water_phantom", "slab_heterogeneity", "ct_patient"])
        histories = st.number_input("Number of Histories", value=100000, step=50000)

    if st.button("Generate TOPAS Deck"):
        try:
            deck = generate_topas_deck(particle, energy, geom, number_of_histories=histories)
            st.success("Deck generated and passed clinical physics bounds (0.01 - 250 MeV)!")
            st.code(deck, language="bash")
        except BeamEnergyBoundsError as e:
            st.error(f"Physics Guardrail Rejection: {e}")

# -----------------------------------------------------------------------------
# Mode 5: Radiobiology
# -----------------------------------------------------------------------------
elif agent_mode == "Radiobiology (TCP / NTCP)":
    st.subheader("Radiobiological Modeling (LKB NTCP & Poisson TCP)")
    model = st.radio("Model Type", ["LKB", "Poisson_LQ"])
    if model == "LKB":
        c1, c2, c3 = st.columns(3)
        with c1:
            td50 = st.number_input("TD50 (Gy)", value=65.0)
        with c2:
            m = st.number_input("Slope (m)", value=0.175)
        with c3:
            n = st.number_input("Volume effect (n)", value=0.05)

        dummy_dvh = {"dose_bins_Gy": [0, 20, 40, 60], "volume_percent": [100, 90, 40, 0]}
        res = calculate_tcp_ntcp(dummy_dvh, "LKB", {"TD50": td50, "m": m, "n": n})
        st.write("Result:", res)

# -----------------------------------------------------------------------------
# Mode 6: REPL Sandbox
# -----------------------------------------------------------------------------
elif agent_mode == "Stateful Python REPL Sandbox":
    st.subheader("Stateful Python REPL Sandbox")
    code = st.text_area("Write Python code to execute:", value="x = np.linspace(0, 10, 50)\nprint('Mean x:', np.mean(x))")
    if st.button("Run Code"):
        repl_res = st.session_state.agent.execute_code(code)
        if repl_res["success"]:
            st.success("Execution Successful")
            if repl_res["stdout"]:
                st.text(repl_res["stdout"])
            if repl_res["artifacts"]:
                for art in repl_res["artifacts"]:
                    st.image(art)
        else:
            st.error(repl_res["error"])
