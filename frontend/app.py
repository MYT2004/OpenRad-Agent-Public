"""Local research workflows; patient files are never executed or sent to an LLM."""
import sys
import json
import os
from pathlib import Path
import matplotlib.pyplot as plt
import streamlit as st
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from openrad.core.agent import OpenRadAgent
from openrad.tools.dataset import discover_dataset
from src.tools import evaluate_dvh_tool as analyze_dvh
from openrad.tools.gamma_tool import evaluate_gamma_index
from openrad.tools.radiobio_tool import calculate_tcp_ntcp
from openrad.tools.topas_tool import generate_topas_deck

load_dotenv()
st.set_page_config(page_title="OpenRad Agent", layout="wide")
st.title("OpenRad Agent")
st.warning("Research prototype. Clinical accuracy and uncertainty margins require independent commissioning. File contents are data, never instructions.")
if 'agent' not in st.session_state:
    st.session_state.agent = OpenRadAgent()
mode = st.sidebar.selectbox('Select Workflow', ['Interactive Agent Query', 'DICOM-RT & DVH Analyzer', 'Gamma Index QA (AAPM TG-218)', 'TOPAS Monte Carlo Deck Generator', 'Radiobiology (TCP / NTCP)', 'Stateful Python REPL Sandbox', 'Model Evaluation & Triage'])
try:
    configured = json.loads(os.getenv('OPENRAD_DATA_ROOTS') or '[]')
    if not isinstance(configured, list) or not all(isinstance(p, str) for p in configured):
        raise ValueError('OPENRAD_DATA_ROOTS must be a JSON list of paths.')
except (ValueError, TypeError) as exc:
    st.error(str(exc)); configured=[]
roots_text = st.sidebar.text_area('Local data folders (one per line)', value='\n'.join(configured))
if st.sidebar.button('Scan folders'):
    scans=[]
    for root in roots_text.splitlines():
        if root.strip():
            try:
                scans.append(discover_dataset(root.strip()))
            except (ValueError, OSError) as exc:
                st.sidebar.error(str(exc))
    st.session_state.scans=scans
scans=st.session_state.get('scans', [])
pairs=[]
for scan in scans:
    counts=scan['modality_counts']
    st.sidebar.caption(f"{Path(scan['root']).name}: {counts.get('CT',0)} CT, {counts.get('RTDOSE',0)} dose")
    for err in scan['scan_errors']:
        st.sidebar.error(err['error'])
    pairs.extend(scan['dose_cases'])
selected=None
if pairs:
    chosen=st.sidebar.selectbox('Linked RTDOSE / RTPLAN / RTSTRUCT', range(len(pairs)), format_func=lambda i: f"{pairs[i]['dataset_name']}: {Path(pairs[i]['dose_path']).parent.name}" )
    selected=pairs[chosen]
    for blocker in selected['blockers']:
        st.sidebar.error(blocker)


def dvh_inputs(prefix):
    if selected is None:
        st.info('Scan and select a dataset in the sidebar.')
        return None
    with st.expander('Source files and provenance'):
        st.json({k: selected[k] for k in ('dose_path','plan_path','struct_path')})
    if selected['blockers']:
        st.error('Selected pair is blocked: ' + '; '.join(selected['blockers']))
        return None
    with st.expander('Structure naming review (AAPM TG-263 Standards)'):
        st.caption('Evaluates contour names against AAPM TG-263 standardized nomenclature. Legacy aliases require human confirmation.')
        st.dataframe([
            {
                'ROI (Source)': r['name'],
                'TG-263 Standard Name': r['nomenclature'].get('canonical_name') or 'Non-standard',
                'Nomenclature Status': r['nomenclature']['status'],
            }
            for r in selected['rois']
        ], use_container_width=True)
    options=[r['name'] for r in selected['rois']]
    defaults=[n for n in options if n.casefold()=='brainstem']
    names=st.multiselect('Exact source ROI names', options, default=defaults, key=prefix+'_names')
    from src.tools import BUILTIN_ROI_ALIASES
    raw=st.text_area('Human-reviewed legacy ROI mapping (JSON)', value='{}', key=prefix+'_map', help='Example after anatomical review: {"Cord":"SpinalCord"}. Built-in aliases (Cord->SpinalCord, RT Parotid->Parotid_R) are applied automatically.')
    try:
        mappings=json.loads(raw)
        if not isinstance(mappings, dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in mappings.items()):
            raise ValueError('Mappings must be name-to-name JSON strings.')
        effective_mappings = dict(BUILTIN_ROI_ALIASES)
        effective_mappings.update(mappings)
    except ValueError as exc:
        st.error(str(exc));return None
    return dict(dicom_rtstruct_path=selected['struct_path'],dicom_rtdose_path=selected['dose_path'],roi_names=names,reviewed_name_map=effective_mappings,dicom_rtplan_path=selected['plan_path'])


if mode=='Interactive Agent Query':
    st.subheader('Autonomous Medical Physics Intelligence Agent')
    with st.expander('ℹ️ User Guide & Agent Instructions', expanded=True):
        st.markdown(r"""
        **How to interact with the Autonomous Agent:**
        1. **Task Execution**: Enter a natural language medical physics task in the box below.
        2. **Physics Guardrails**: Every tool invocation is governed by fail-closed clinical rules (absorbed dose $\ge 0$ Gy, beam energy $0.01 - 250$ MeV, orthogonal frame).
        3. **Deterministic Workflows**: Natural language instructions are resolved into typed deterministic tools (`analyze_dvh`, `evaluate_gamma_index`, `generate_topas_deck`, `verify_model_output`).
        
        **Example Prompts:**
        - `Calculate DVH metrics for Brainstem and SpinalCord` (with dataset selected)
        - `Generate 150 MeV proton TOPAS deck in water phantom`
        - `Evaluate 3%/3mm gamma index between reference and evaluated dose`
        - `Verify clinical dose model safety and generate follow up actions report`
        """)
    query=st.text_input('Task', value='Calculate DVH metrics')
    args=dvh_inputs('agent') if any(w in query.lower() for w in ('dvh','dose volume','rtstruct','rtdose')) else None
    if st.button('Execute Task'):
        result=st.session_state.agent.run(query, context={'dvh':args} if args and args['roi_names'] else {})
        (st.success if result.success else st.error)(result.response)
        for rec in result.tool_records:
            if rec.error: st.error(rec.error)
            if isinstance(rec.output,dict):
                out = rec.output
                if 'clinical_release' in out or 'limitations' in out:
                    st.warning("⚠️ **RESEARCH USE ONLY — NOT FOR CLINICAL RELEASE**\n\n" +
                               "\n".join(f"- {lim}" for lim in out.get('limitations', [])))
                if 'nomenclature' in out and isinstance(out['nomenclature'], dict):
                    nom = out['nomenclature']
                    st.info(f"📋 **Nomenclature Review**: {nom.get('standard', 'AAPM TG-263')} (Catalog: {nom.get('vocabulary_version', '20170815')})")
                    structs = nom.get('structures', [])
                    if structs:
                        with st.expander('TG-263 Structure Mapping Details', expanded=False):
                            st.dataframe([
                                {
                                    'Original Name': s.get('original_name'),
                                    'Canonical Name': s.get('canonical_name') or 'Non-standard',
                                    'Status': s.get('status'),
                                    'Notes': s.get('warning') or s.get('error') or 'Standard compliant'
                                }
                                for s in structs
                            ], use_container_width=True)
                with st.expander('Technical Tool Record', expanded=False):
                    st.json({k: v for k, v in out.items() if k not in ('clinical_release', 'limitations', 'nomenclature')})

elif mode=='DICOM-RT & DVH Analyzer':
    st.subheader('DVH Analysis with AAPM TG-263 & TG-53 QA Standards')
    with st.expander('ℹ️ Workflow Instructions & Dosimetric Standards', expanded=False):
        st.markdown(r"""
        **Step-by-Step Instructions:**
        1. **Select Dataset**: Scan local directories via the sidebar and select a linked RTDOSE / RTSTRUCT pair.
        2. **Nomenclature Review**: Check the **Structure naming review** expander to see TG-263 standardization status.
        3. **Select Structures**: Choose exact contour names to compute cumulative Dose-Volume Histograms.
        4. **Compute Metrics**: Press **Compute DVH** to calculate TG-263 metrics ($D_{95\%}$, $D_{50\%}$, $D_{2\%}$, $V_{50\text{Gy}}$, $\bar{D}$) and inspect the dose curve.
        """)
    args=dvh_inputs('dvh')
    if st.button('Compute DVH', disabled=not args or not args['roi_names']):
        try:
            result=analyze_dvh(**args)
            nom = result.get('nomenclature', {})
            structs = nom.get('structures', [])
            compliant_count = sum(1 for s in structs if s.get('status') == 'standard_primary')
            st.info(f"📋 **TG-263 Nomenclature Compliance**: {nom.get('standard', 'AAPM TG-263')} | Catalog: {nom.get('vocabulary_version', '20170815')} | Compliant: {compliant_count}/{len(structs)} structures")
            with st.expander('TG-263 Structure Mapping Details', expanded=False):
                st.dataframe([
                    {
                        'Original Name': s.get('original_name'),
                        'Canonical Name': s.get('canonical_name') or 'Non-standard',
                        'Status': s.get('status'),
                        'Notes': s.get('warning') or s.get('error') or 'Standard compliant'
                    }
                    for s in structs
                ], use_container_width=True)
            fig,ax=plt.subplots(figsize=(8,5));plotted=False
            for name, entry in result['structures'].items():
                if not entry.get('found'):
                    st.error(f"{name}: {entry['error']}");continue
                st.write(f"### Structure: `{name}`")
                st.dataframe([entry['tg263_metrics'] | {'Volume [cc]':entry['volume_cc'],'Contour spacing [mm]':entry['contour_plane_thickness_mm']}], use_container_width=True)
                curve=entry['dvh_curve']; ax.plot(curve['dose_bins_Gy'],curve['volume_percent'],label=name);plotted=True
            if plotted:
                ax.set(xlabel='Dose (Gy)',ylabel='Volume (%)');ax.legend();st.pyplot(fig)
                st.session_state.last_dvh=result
            plt.close(fig)
            st.warning("⚠️ **RESEARCH USE ONLY — NOT FOR CLINICAL RELEASE**\n\n" + "\n".join(f"- {lim}" for lim in result.get('limitations', [])))
        except (ValueError, OSError, AttributeError) as exc:
            st.error(str(exc))

elif mode=='Gamma Index QA (AAPM TG-218)':
    st.subheader('Independent Dose Comparison & AAPM TG-218 Quality Assurance')
    with st.expander('ℹ️ AAPM TG-218 Criteria & User Guide', expanded=False):
        st.markdown(r"""
        **Clinical Tolerances (AAPM TG-218):**
        | Evaluation Criterion | Candidate Pass | Flagged for Review | Immediate Reject |
        | :--- | :--- | :--- | :--- |
        | **Standard Gamma (3% / 3 mm)** | $\ge 95.0\%$ | $90.0\% - 94.9\%$ | $< 90.0\%$ |
        | **Tight Margin Gamma (2% / 2 mm)** | $\ge 90.0\%$ | $85.0\% - 89.9\%$ | $< 85.0\%$ |
        | **Low-Dose Cutoff Threshold** | 10% of maximum dose | Fixed cutoff | Excludes low-dose noise |

        **Instructions:**
        - Enter absolute filesystem paths to two independent dose distributions (DICOM RTDOSE `.dcm` or NumPy `.npy`).
        - For non-DICOM NumPy arrays, specify voxel spacing in mm per axis: `[dz, dy, dx]`. Units must be Gy.
        - Self-comparisons (comparing a file to itself) are physically invalid and rejected by safety guardrails.
        """)
    reference=st.text_input('Reference RTDOSE/NPY path', value=selected['dose_path'] if selected else '')
    evaluated=st.text_input('Independent evaluated dose path', value='')
    dt=st.number_input('Dose Tolerance (%)',value=3.,min_value=.01)
    dr=st.number_input('Distance Tolerance (mm)',value=2.,min_value=.01)
    cutoff=st.number_input('Low-dose Cutoff (%)',value=10.,min_value=0.,max_value=100.)
    spacing=st.text_input('Non-DICOM spacing in mm, per array axis (JSON; dose must be Gy)',value='[]')
    if st.button('Evaluate Gamma Index'):
        try:
            if not reference or not evaluated or Path(reference).resolve()==Path(evaluated).resolve():
                raise ValueError('Provide two independent dose files; a self-comparison cannot verify patient QA.')
            result=evaluate_gamma_index(reference,evaluated,dt,dr,cutoff,reference_spacing_mm=json.loads(spacing),evaluated_spacing_mm=json.loads(spacing))
            st.warning("⚠️ **RESEARCH USE ONLY — NOT FOR CLINICAL RELEASE**\n\n" + "\n".join(f"- {lim}" for lim in result.get('limitations', [])))
            c1, c2, c3 = st.columns(3)
            c1.metric("Passing Rate", f"{result.get('passing_rate', 0.0):.2f}%")
            c2.metric("Mean Gamma", f"{result.get('average_gamma', 0.0):.3f}")
            c3.metric("Max Gamma", f"{result.get('max_gamma', 0.0):.3f}")
            with st.expander("Detailed QA Evaluation Data", expanded=False):
                st.json({k: v for k, v in result.items() if k not in ('clinical_release', 'limitations')})
        except (ValueError, OSError, AttributeError) as exc:
            st.error(str(exc))

elif mode=='TOPAS Monte Carlo Deck Generator':
    st.subheader('Research TOPAS / Geant4 Parameter Deck Generator')
    with st.expander('ℹ️ TOPAS Deck Instructions & Physical Bounds', expanded=False):
        st.markdown(r"""
        **Generator Specifications:**
        - **Supported Particles**: Protons (`proton`), electrons (`e-`), photons/gammas (`gamma`), neutrons (`neutron`).
        - **Beam Kinetic Energy Bounds**: Must satisfy clinical radiotherapy limits: $0.01\text{ MeV} \le E \le 250\text{ MeV}$.
        - **Geometries**: Standard $30 \times 30 \times 30\text{ cm}$ water phantom (`water_phantom`) or slab heterogeneity.
        - **Scorer**: DoseToMedium mesh scoring output.
        """)
    particle=st.selectbox('Particle Type',['proton','e-','gamma','neutron'])
    energy=st.number_input('Beam Energy (MeV)',value=150.)
    geom=st.selectbox('Geometry',['water_phantom','slab_heterogeneity'])
    histories=st.number_input('Number of Histories',value=100000,min_value=1,step=10000)
    st.info('Patient CT transport is unavailable. Generated decks require TOPAS runtime and beam-model verification.')
    if st.button('Generate TOPAS Deck'):
        try:st.code(generate_topas_deck(particle,energy,geom,number_of_histories=histories))
        except ValueError as exc:st.error(str(exc))

elif mode=='Model Evaluation & Triage':
    from src.decision import EvaluationRequest
    from src.evaluation import evaluate_model
    from src.storage import StorageManager, session_scope
    st.subheader('High-Consequence Model Evaluation & Triage Harness')
    st.info('APPROVED means a research candidate for this case. Missing calibration or OOD evidence requires review. Raw data stays read-only.')
    
    with st.expander('📖 Evaluation Manifest JSON Guide: Required Fields & Schema', expanded=False):
        st.markdown(r"""
        ### What is supposed to be input in the Evaluation JSON?
        The evaluation harness programmatically verifies computational dose prediction models against AAPM TG-218 and deterministic physics rules. Supply a valid JSON object matching the `EvaluationRequest` schema:

        | Field Name | Type | Description | Example / Required Format |
        | :--- | :--- | :--- | :--- |
        | `model_name` | String | Pseudonym / model identifier (alphanumeric, max 64 chars) | `"RadNet_v1"` |
        | `dataset_id` | String | Dataset or cohort identifier (alphanumeric, max 64 chars) | `"HNSCC_Phantom_01"` |
        | `model_kind` | String | Model modality | `"dose_predictor"` (or `"monte_carlo"`, `"auto_segmentation"`) |
        | `model_weights_path` | String | Absolute path to model weights file for SHA-256 audit hashing | `"/data/weights.pt"` |
        | `input_paths` | List[str] | List of input image/DICOM series paths | `["/data/ct_scan.dcm"]` |
        | `reference_path` | String | Ground-truth reference 3D dose grid in NumPy `.npy` format (Gy) | `"/data/ref_dose.npy"` |
        | `prediction_path` | String | Evaluated model predicted 3D dose grid in NumPy `.npy` format (Gy) | `"/data/pred_dose.npy"` |
        | `image_grid` | Object | Geometric grid metadata for image frame | `{"shape": [Z,Y,X], "spacing_mm": [dz,dy,dx], "origin_mm": [z0,y0,x0], "frame_id": "FRAME_01", "dose_units": "Gy"}` |
        | `reference_grid` | Object | Geometric grid metadata for reference dose | Identical shape, spacing, and frame_id to prediction |
        | `prediction_grid` | Object | Geometric grid metadata for predicted dose | Must match reference_grid alignment |
        | `prescription_gy` | Float | Prescribed target dose in Gray | `50.0` |
        | `target_mask_path` | String | Binary 3D mask for PTV/target volume (`.npy`) | `"/data/ptv_mask.npy"` |
        | `oar_mask_paths` | Dict | Map of canonical TG-263 OAR names to binary mask files (`.npy`) | `{"SpinalCord": "/data/cord.npy", "Brainstem": "/data/brainstem.npy"}` |
        | `oar_limits_gy` | Dict | Map of serial organ tolerance dose ceilings in Gray | `{"SpinalCord": 45.0, "Brainstem": 54.0}` |
        | `energy_mev` | Optional[Float] | Beam kinetic energy in MeV (checked against 0.01 - 250 MeV) | `6.0` |
        | `uncertainty_std_path` | Optional[Str] | Optional 3D voxel standard deviation map in Gy | `"/data/uncertainty_sd.npy"` |
        """)

    with st.expander('🎯 Clinical QA Decision Policy & Tolerance Matrix', expanded=False):
        st.markdown(r"""
        | QA Metric / Physical Rule | Candidate (APPROVED) | Review (FLAGGED_FOR_REVIEW) | Rejection (REJECTED) |
        | :--- | :--- | :--- | :--- |
        | **Absorbed Dose Non-Negativity** | $D(\vec{r}) \ge 0.0$ Gy everywhere | N/A | Any $D < 0.0$ Gy (CT rescale error) |
        | **Standard Gamma (3% / 3 mm)** | $\ge 95.0\%$ | $90.0\% - 94.9\%$ | $< 90.0\%$ |
        | **Tight Margin Gamma (2% / 2 mm)** | $\ge 90.0\%$ | $85.0\% - 89.9\%$ | $< 85.0\%$ |
        | **TG-218 Reference Gamma (3% / 2 mm)**| $\ge 95.0\%$ | $90.0\% - 94.9\%$ | $< 90.0\%$ |
        | **PTV Coverage ($D_{95\%} / D_{\text{rx}}$)** | $\ge 95.0\%$ | $93.0\% - 94.9\%$ | $< 93.0\%$ (Target under-dosage) |
        | **Mean Absolute Error (MAE / $D_{\text{rx}}$)**| $< 1.5\%$ | $1.5\% - 3.0\%$ | $> 3.0\%$ |
        | **Serial OAR $D_{\text{max}} / D_{\text{limit}}$**| $< 98.0\%$ | $98.0\% - 100.0\%$ | $> 100.0\%$ (Lethal toxicity breach) |
        | **High Uncertainty / Gradient Overlap** | No overlap | Overlap within 3 mm of OAR | N/A |
        """)

    manifest = st.text_area('Evaluation manifest JSON', value=st.session_state.get('manifest_text', '{}'), height=240)
    if st.button('Evaluate supplied model output'):
        try:
            request = EvaluationRequest.model_validate_json(manifest)
            manager = StorageManager(os.getenv('STORAGE_DIR', './storage/sessions'))
            with session_scope(manager):
                result = evaluate_model(request)
            st.session_state.model_evaluation = result
        except Exception as exc:
            st.error(f"Evaluation rejected: {str(exc)}")
    if 'model_evaluation' in st.session_state:
        result = st.session_state.model_evaluation
        st.metric('Research triage', result['status'])
        st.dataframe(result['rules'], use_container_width=True)
        st.warning("⚠️ **RESEARCH USE ONLY — NOT FOR CLINICAL RELEASE**\n\n" + "\n".join(f"- {lim}" for lim in result.get('limitations', [])))
        with st.expander("Evaluation Provenance & Audit Payload", expanded=False):
            st.json({k: v for k, v in result.items() if k not in ('rules', 'limitations', 'clinical_release', 'status')})
        manager = StorageManager(os.getenv('STORAGE_DIR', './storage/sessions'))
        for artifact in result['artifacts']:
            st.image(str(Path(manager.get_artifacts_dir(result['session_id'])) / Path(artifact).name))
    st.caption('Signed review is available through the REST API using operator-registered Ed25519 reviewer keys. Automated decisions remain immutable.')

elif mode=='Radiobiology (TCP / NTCP)':
    st.subheader('Research Radiobiological Modeling (LKB NTCP & Poisson TCP)')
    with st.expander('ℹ️ Radiobiology Modeling Guidelines & Parameters', expanded=False):
        st.markdown("""
        **Supported Models:**
        1. **Lyman-Kutcher-Burman (LKB) NTCP**:
           - **$TD_{50}$**: Tolerance dose in Gy giving 50% complication probability.
           - **$m$**: Slope parameter for sigmoid steepness.
           - **$n$**: Volume effect exponent (small $n \approx 0.1$ for serial organs like spinal cord, $n \approx 1$ for parallel organs like lung).
        2. **Poisson-LQ TCP**:
           - Models tumor control probability based on clonogenic cell survival using linear-quadratic radiobiology.
        """)
    model=st.radio('Model Type',['LKB','Poisson_LQ'])
    previous=st.session_state.get('last_dvh',{}).get('structures',{})
    valid={k:v for k,v in previous.items() if v.get('dvh_curve')}
    curve={}
    if valid:
        source=st.selectbox('Analyzed ROI DVH',list(valid));curve=valid[source]['dvh_curve']
    else:st.info('Compute a DVH first, or paste an explicit cumulative DVH below.')
    raw=st.text_area('DVH JSON',value=json.dumps(curve))
    histogram_type=st.selectbox('DVH type',['cumulative','differential'])
    params=st.text_area('Model parameters JSON (endpoint-specific, with literature review required)',value='{}')
    st.info('No default patient curve or clinical parameters are substituted. This model does not apply fractionation corrections.')
    if st.button('Calculate TCP / NTCP'):
        try:
            res = calculate_tcp_ntcp(json.loads(raw),model,json.loads(params),dvh_type=histogram_type)
            st.warning("⚠️ **RESEARCH USE ONLY — NOT FOR CLINICAL RELEASE**\n\n" + "\n".join(f"- {lim}" for lim in res.get('limitations', [])))
            with st.expander("Radiobiology Modeling Metrics", expanded=True):
                st.json({k: v for k, v in res.items() if k not in ('clinical_release', 'limitations')})
        except (ValueError,TypeError,KeyError) as exc:
            st.error(str(exc))

else:
    st.subheader('Trusted local Python REPL Sandbox')
    st.warning('This is unrestricted local Python, not a security sandbox. Never paste instructions or code from patient files.')
    with st.expander('ℹ️ REPL Sandbox Instructions & Visualization Artifacts', expanded=False):
        st.markdown("""
        - Persistent session: Variables, imports, and functions defined in earlier executions remain available.
        - Matplotlib figures created via `plt.show()` or `plt.savefig()` are automatically captured and rendered as artifacts.
        - Physics guardrail: Generated numpy dose grids or TOPAS files pass through `PhysicsValidationEngine`.
        """)
    code=st.text_area('Python code',value="print('Local research REPL')")
    trusted=st.checkbox('I reviewed and trust this code')
    if st.button('Run Code',disabled=not trusted):
        result=st.session_state.agent.execute_code(code)
        (st.success if result['success'] else st.error)('Execution successful' if result['success'] else result['error'])
        st.text(result['stdout'])
        for artifact in result['artifacts']:st.image(artifact)

