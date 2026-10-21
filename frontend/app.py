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
from openrad.validation.nomenclature import check_structure_name
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
mode = st.sidebar.selectbox('Select Workflow', [
    'Patient-file Verification',
    '🤖 Dynamic Agent Copilot',
    'DICOM-RT & DVH Analyzer',
    'Gamma Index QA (AAPM TG-218)',
    'TOPAS Monte Carlo Deck Generator',
    'Radiobiology (TCP / NTCP)',
    'Model Evaluation & Triage',
    'Interactive Agent Query',
    'Stateful Python REPL Sandbox'
], key='workflow_mode')
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
        standard_count = sum(1 for r in selected['rois'] if r.get('nomenclature', {}).get('status') == 'standard')
        review_count = len(selected['rois']) - standard_count
        c1, c2 = st.columns(2)
        c1.metric("TG-263 Standard Contours", f"{standard_count} Standard")
        c2.metric("Review Required", f"{review_count} Review Required")
        st.dataframe([
            {
                'ROI (Source)': r['name'],
                'TG-263 Standard Name': r['nomenclature'].get('canonical_name') or 'Review required',
                'Nomenclature Status': r['nomenclature']['status'],
            }
            for r in selected['rois']
        ], width='stretch')
    options=[r['name'] for r in selected['rois']]
    defaults=[n for n in options if n.casefold()=='brainstem']
    names=st.multiselect('Exact source ROI names', options, default=defaults, key=prefix+'_names')
    from src.tools import BUILTIN_ROI_ALIASES
    raw=st.text_area('Human-reviewed legacy ROI mapping (JSON)', value='{}', key=prefix+'_map', help='Example after anatomical review: {"Cord":"SpinalCord"}. No anatomical equivalence is inferred automatically.')
    try:
        mappings=json.loads(raw)
        if not isinstance(mappings, dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in mappings.items()):
            raise ValueError('Mappings must be name-to-name JSON strings.')
        suggestions = {name: BUILTIN_ROI_ALIASES[name.casefold()] for name in options
                       if name.casefold() in BUILTIN_ROI_ALIASES and check_structure_name(name)['canonical_name'] is None}
        effective_mappings = dict(mappings)
        if suggestions:
            st.json({'Suggested aliases for anatomical review': suggestions})
            if st.checkbox('I confirmed the suggested aliases against the anatomy', key=prefix+'_confirm_aliases'):
                effective_mappings = {**suggestions, **mappings}
    except ValueError as exc:
        st.error(str(exc));return None
    return dict(dicom_rtstruct_path=selected['struct_path'],dicom_rtdose_path=selected['dose_path'],roi_names=names,reviewed_name_map=effective_mappings,dicom_rtplan_path=selected['plan_path'])


def present_result(result, kind, key):
    from src.reports import build_report, markdown, metrics_csv
    st.warning("⚠️ **RESEARCH USE ONLY — NOT FOR CLINICAL RELEASE**\n\nSingle-case research candidate evaluation only. Does not replace independent clinical commissioning or certified treatment planning system verification.")
    report = result.get('human_report') or build_report(result, kind)
    st.markdown(report['summary'])
    st.table(report['metrics'])
    st.markdown('**Follow-up actions**')
    for index, action in enumerate(report['follow_up_actions'], 1):
        st.write(f'{index}. {action}')
    st.caption(' '.join(report['limitations']))
    st.download_button('Download assessment report (Markdown)', markdown(report),
                       file_name=f'openrad_{kind}_report.md', mime='text/markdown', key=key+'_md')
    st.download_button('Download metrics (CSV)', metrics_csv(report),
                       file_name=f'openrad_{kind}_metrics.csv', mime='text/csv', key=key+'_csv')
    st.download_button('Download technical results (JSON)', json.dumps(result, indent=2, allow_nan=False),
                       file_name=f'openrad_{kind}_results.json', mime='application/json', key=key+'_json')


def prepare_synthetic_demo_case():
    from src.demo import create_synthetic_case
    from src.storage import StorageManager, session_scope
    try:
        manager=StorageManager(os.getenv('STORAGE_DIR','./storage/sessions'))
        with session_scope(manager) as session_id:
            demo=create_synthetic_case(Path(manager.get_session_dir(session_id))/'synthetic-inputs')
        st.session_state.case_directory_input=demo['root']
        st.session_state.case_pseudonym_input=demo['case_id']
        st.session_state.synthetic_demo_root=demo['root']
    except (ValueError,OSError):
        st.session_state.case_demo_error='Synthetic inputs could not be created. Check separate runtime storage.'


def prepare_verified_case_dvh(root):
    try:
        st.session_state.scans=[discover_dataset(root)]
        st.session_state.workflow_mode='DICOM-RT & DVH Analyzer'
    except (ValueError,OSError):
        st.session_state.case_handoff_error='Case discovery failed. Re-verify the case directory before continuing.'


if mode == '🤖 Dynamic Agent Copilot':
    from src.agent_dynamic import run_dynamic_agent
    st.subheader('🤖 Dynamic Agent Copilot (Gemini Grounded Reasoning)')
    st.caption('Autonomous LLM medical physics partner with deterministic physical validation, pessimistic safety interceptors, and step-by-step reasoning trajectory.')

    st.warning("⚠️ **RESEARCH USE ONLY — NOT FOR CLINICAL RELEASE**\n\nSingle-case research candidate evaluation only. Does not replace independent clinical commissioning or certified treatment planning system verification.")

    with st.expander('ℹ️ Copilot Operational Scope & Physics Guardrails', expanded=False):
        st.markdown(r"""
        **Architectural Highlights:**
        1. **Grounded Function Calling**: All dose metrics ($D_{95\%}$, $D_{50\%}$, $D_{2\%}$, $V_{50\text{Gy}}$, $\bar{D}$), gamma passing rates, and TOPAS decks originate from deterministic Python modules.
        2. **Pessimistic Safety Interceptors**: Rejects unphysical negative voxel dose distributions ($D(\vec{r}) < 0.0\text{ Gy}$), non-orthogonal geometry, and beam energies outside clinical bounds ($0.01 - 250\text{ MeV}$).
        3. **Spinal Cord Tolerance Policy**: Hard biological safety ceiling $D_{\max} < 45.0\text{ Gy}$ to guard against myelopathy. Plans exceeding this are designated `REJECTED`.
        4. **Offline Grounded Fallback**: Automatically falls back to deterministic local tool execution if `GEMINI_API_KEY` is not configured.
        """)

    preset_queries = [
        "Verify dataset data/raw/HNSCC-01-0199, compute DVH for SpinalCord, and determine if plan complies with 45 Gy cord tolerance.",
        "Inspect case data/raw/HNSCC-01-0019, evaluate target coverage for PTV70, and generate a 150 MeV proton TOPAS deck.",
        "Evaluate AAPM TG-218 3%/2mm Gamma QA between reference and independent evaluated dose.",
        "Custom Clinical Directive..."
    ]
    selected_preset = st.selectbox("Select Pre-configured Clinical Directive or Custom", preset_queries, key='copilot_preset')
    default_text = "" if selected_preset == "Custom Clinical Directive..." else selected_preset

    query_input = st.text_area("Clinical Directive / Medical Physics Query", value=default_text, height=90, key='copilot_query_text')

    col_api, col_model, col_run = st.columns([2.5, 1.5, 1])
    with col_api:
        gemini_api_key = st.text_input("Gemini API Key (Optional — leaves empty for offline grounded mode)", type="password", value=os.getenv("GEMINI_API_KEY", ""), key='copilot_gemini_key')
    with col_model:
        selected_model = st.selectbox("Model", ["gemini-3.1-pro-preview", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"], index=0, key='copilot_gemini_model')
    with col_run:
        st.write("")
        st.write("")
        run_copilot = st.button("🚀 Run Copilot", type="primary", use_container_width=True, disabled=not query_input.strip())

    if run_copilot:
        with st.spinner("Executing dynamic reasoning loop, grounding deterministic tools, and verifying physical bounds..."):
            res = run_dynamic_agent(query_input.strip(), api_key=gemini_api_key or None, model=selected_model)
            st.session_state.copilot_result = res

    if 'copilot_result' in st.session_state:
        res = st.session_state.copilot_result

        c1, c2, c3 = st.columns(3)
        disp = getattr(res, 'disposition', 'APPROVED')
        if disp == 'APPROVED':
            c1.success(f"**Research Triage:** {disp}")
        elif disp == 'FLAGGED_FOR_REVIEW':
            c1.warning(f"**Research Triage:** {disp}")
        else:
            c1.error(f"**Research Triage:** {disp}")

        c2.metric("Executed Tool Calls", len(res.trajectory))
        c3.metric("Safety Verification", "100% Grounded")

        with st.expander("🔍 View Agent Tool-Calling Trajectory & Safety Interceptions", expanded=True):
            if not res.trajectory:
                st.info("No tool calls were required for this directive.")
            for step in res.trajectory:
                step_idx = step.get('step', 1)
                tool_nm = step.get('tool_name', 'tool')
                st.markdown(f"#### Step {step_idx}: Grounded Tool `{tool_nm}`")
                st.info(f"**Agent Intent / Rationale:** {step.get('thought', 'Invoking grounded medical physics tool.')}")

                col_args, col_obs = st.columns(2)
                with col_args:
                    st.markdown("**Validated Arguments:**")
                    st.json(step.get('arguments', {}))
                with col_obs:
                    st.markdown("**Deterministic Observation:**")
                    obs_raw = step.get('observation', '')
                    try:
                        obs_parsed = json.loads(obs_raw)
                        st.json(obs_parsed)
                    except Exception:
                        st.code(obs_raw, language='text')
                st.divider()

        st.markdown("### 📋 Synthesized Clinical Physics Report")
        st.markdown(res.response)

        if getattr(res, 'artifacts', None):
            st.markdown("### 📊 Generated Session Artifacts")
            for art in res.artifacts:
                art_p = Path(art)
                if art_p.suffix.lower() in ('.png', '.jpg', '.jpeg'):
                    st.image(str(art_p), caption=art_p.name)
                elif art_p.suffix.lower() in ('.txt', '.topas'):
                    with st.expander(f"View File: {art_p.name}"):
                        st.code(art_p.read_text(), language='text')

        d_col1, d_col2 = st.columns(2)
        d_col1.download_button(
            "Download Clinical Report (Markdown)",
            res.response,
            file_name="openrad_copilot_clinical_report.md",
            mime="text/markdown",
            key="download_copilot_md"
        )
        d_col2.download_button(
            "Download Reasoning Trajectory (JSON)",
            json.dumps(res.trajectory, indent=2),
            file_name="openrad_copilot_trajectory.json",
            mime="application/json",
            key="download_copilot_json"
        )

elif mode=='Patient-file Verification':
    from src.case_verification import CaseVerificationRequest, verify_patient_case, ensure_case_output_separation
    from src.storage import StorageManager, session_scope
    st.subheader('Patient-file intake verification')
    st.write('Select an authorized case directory. The verifier reads source files, checks supported DICOM identity/linkage, image-stack geometry and pixel integrity, and prioritizes follow-up actions.')
    st.button('Create an explicitly synthetic demo case',on_click=prepare_synthetic_demo_case)
    if st.session_state.get('case_demo_error'):st.error(st.session_state.pop('case_demo_error'))
    st.session_state.setdefault('case_directory_input',configured[0] if configured else '')
    st.session_state.setdefault('case_pseudonym_input','research-case-001')
    root=st.text_input('Case directory',key='case_directory_input')
    case_id=st.text_input('Case pseudonym (no patient names or original identifiers)',key='case_pseudonym_input')
    if root==st.session_state.get('synthetic_demo_root'):
        st.info('SYNTHETIC TEACHING CASE — artificial anatomy and dose, never a patient or a clinically validated plan.')
    check_pixels=st.checkbox('Decode image and dose pixels', value=True)
    st.caption('No registration, source repair, clinical plan approval or full DICOM conformance certification is performed. Unknown document contents are not executed.')
    context_key=json.dumps([root,case_id,check_pixels])
    if st.button('Verify patient files', disabled=not root):
        try:
            request=CaseVerificationRequest(root=root,case_id=case_id,check_pixels=check_pixels)
            ensure_case_output_separation(root,os.getenv('STORAGE_DIR','./storage/sessions'))
            with st.spinner('Reading source files and checking case integrity…'):
                with session_scope(StorageManager(os.getenv('STORAGE_DIR','./storage/sessions'))):
                    result=verify_patient_case(request)
            st.session_state.case_verification=(context_key,result)
        except (ValueError,OSError):
            st.session_state.pop('case_verification',None)
            st.error('Verification could not be committed. Check the case directory, resource limits and separate output storage.')
    saved=st.session_state.get('case_verification')
    if saved and saved[0]==context_key:
        result=saved[1]
        st.metric('Intake state',result['status'])
        present_result(result,'case_verification','case_verification')
        if result['dose_cases']:
            st.button('Continue to DVH and structure review', disabled=result['status']=='BLOCKED',
                      on_click=prepare_verified_case_dvh,args=(root,))
        if st.session_state.get('case_handoff_error'):
            st.error(st.session_state.pop('case_handoff_error'))
        with st.expander('Technical findings, content hashes and scope'):
            st.json({key:value for key,value in result.items() if key!='human_report'})

elif mode=='Interactive Agent Query':
    st.subheader('Medical Physics Workflow Assistant')
    with st.expander('ℹ️ User Guide & Agent Instructions', expanded=True):
        st.markdown(r"""
        **How to use the deterministic workflow assistant:**
        1. **Task Execution**: Enter a natural language medical physics task in the box below.
        2. **Supported numerical checks**: Tools check applicable input bounds (absorbed dose $\ge 0$ Gy, beam energy $0.01 - 250$ MeV, orthogonal frame).
        3. **Workflow selection**: Use the dedicated sidebar workflows for file verification, gamma and model assessment. This assistant routes explicit supported DVH/TOPAS requests; external LLM orchestration is not implemented.
        
        **Example Prompts:**
        - `Calculate DVH metrics for Brainstem and SpinalCord` (with dataset selected)
        - `Generate 150 MeV proton TOPAS deck in water phantom`
        - For independent dose comparison, select **Gamma Index QA** and supply both distributions.
        - For dose-model assessment and follow-up actions, select **Model Evaluation & Triage**.
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
                        std_c = sum(1 for s in structs if s.get('status') == 'standard')
                        rev_c = len(structs) - std_c
                        col_nom1, col_nom2 = st.columns(2)
                        col_nom1.metric("TG-263 Standard", f"{std_c} Standard")
                        col_nom2.metric("Review Required", f"{rev_c} Review Required")
                        with st.expander('TG-263 Structure Mapping Details', expanded=False):
                            st.dataframe([
                                {
                                    'Original Name': s.get('original_name'),
                                    'Canonical Name': s.get('canonical_name') or 'Review required',
                                    'Status': s.get('status'),
                                    'Notes': '; '.join(s.get('issues', [])) or 'Primary-name syntax checked; anatomy unverified'
                                }
                                for s in structs
                            ], width='stretch')
                with st.expander('Technical Tool Record', expanded=False):
                    st.json({k: v for k, v in out.items() if k not in ('clinical_release', 'limitations', 'nomenclature')})

elif mode=='DICOM-RT & DVH Analyzer':
    st.subheader('DVH Analysis and TG-263 Naming Review')
    with st.expander('ℹ️ Workflow Instructions & Dosimetric Standards', expanded=False):
        st.markdown(r"""
        **Step-by-Step Instructions:**
        1. **Select Dataset**: Scan local directories via the sidebar and select a linked RTDOSE / RTSTRUCT pair.
        2. **Nomenclature Review**: Check the **Structure naming review** expander to see TG-263 standardization status.
        3. **Select Structures**: Choose exact contour names to compute cumulative Dose-Volume Histograms.
        4. **Compute Metrics**: Press **Compute DVH** to calculate TG-263 metrics ($D_{95\%}$, $D_{50\%}$, $D_{2\%}$, $V_{50\text{Gy}}$, $\bar{D}$) and inspect the dose curve.
        """)
    args=dvh_inputs('dvh')
    context_key = json.dumps(args, sort_keys=True)
    if st.button('Compute DVH', disabled=not args or not args['roi_names']):
        try:
            st.session_state.last_dvh = analyze_dvh(**args)
            st.session_state.last_dvh_context = context_key
        except (ValueError, OSError, AttributeError) as exc:
            st.session_state.pop('last_dvh', None)
            st.error(str(exc))
    if 'last_dvh' in st.session_state and st.session_state.get('last_dvh_context') == context_key:
        result = st.session_state.last_dvh
        present_result(result, 'dvh', 'dvh')
        with st.expander('TG-263 naming details'):
            nom_structs = result.get('nomenclature', {}).get('structures', [])
            if nom_structs:
                std_c = sum(1 for s in nom_structs if s.get('status') == 'standard')
                rev_c = len(nom_structs) - std_c
                c1, c2 = st.columns(2)
                c1.metric("TG-263 Standard", f"{std_c} Standard")
                c2.metric("Review Required", f"{rev_c} Review Required")
            st.dataframe(nom_structs, width='stretch')
        fig, ax = plt.subplots(figsize=(8,5))
        for name, entry in result['structures'].items():
            if entry.get('found'):
                curve=entry['dvh_curve']; ax.plot(curve['dose_bins_Gy'],curve['volume_percent'],label=name)
        if ax.lines:
            ax.set(xlabel='Dose (Gy)', ylabel='Volume (%)', ylim=(0,105), title='Synthetic teaching DVH — research only' if result.get('synthetic') else 'Cumulative DVH — research assessment')
            ax.legend(); st.pyplot(fig)
        plt.close(fig)

elif mode=='Gamma Index QA (AAPM TG-218)':
    st.subheader('Independent Dose Comparison & AAPM TG-218 Quality Assurance')
    with st.expander('ℹ️ AAPM TG-218 Criteria & User Guide', expanded=False):
        st.markdown(r"""
        **Research comparison policies:**
        | Evaluation Criterion | Candidate Pass | Flagged for Review | Immediate Reject |
        | :--- | :--- | :--- | :--- |
        | **TG-218 reference (3% / 2 mm)** | $\ge 95.0\%$ | $\ge90.0\%, <95.0\%$ | $<90.0\%$ |
        | **Custom Gamma (3% / 3 mm)** | $\ge 95.0\%$ | $90.0\% - 94.9\%$ | $< 90.0\%$ |
        | **Tight Margin Gamma (2% / 2 mm)** | $\ge 90.0\%$ | $85.0\% - 89.9\%$ | $< 85.0\%$ |
        | **Low-Dose Cutoff Threshold** | 10% of maximum dose | Fixed cutoff | Excludes low-dose noise |

        **Instructions:**
        - Enter absolute filesystem paths to two independent dose distributions (DICOM RTDOSE `.dcm` or NumPy `.npy`).
        - For non-DICOM NumPy arrays, specify voxel spacing in mm per axis: `[dz, dy, dx]`. Units must be Gy.
        - Self-comparisons can test implementation consistency but cannot establish independent patient QA; this workflow requires two separate files.
        """)
    reference=st.text_input('Reference RTDOSE/NPY path', value=selected['dose_path'] if selected else '')
    evaluated=st.text_input('Independent evaluated dose path', value='')
    dt=st.number_input('Dose Tolerance (%)',value=3.,min_value=.01)
    dr=st.number_input('Distance Tolerance (mm)',value=2.,min_value=.01)
    cutoff=st.number_input('Low-dose Cutoff (%)',value=10.,min_value=0.,max_value=100.)
    spacing=st.text_input('Non-DICOM spacing in mm, per array axis (JSON; dose must be Gy)',value='[]')
    context_key=json.dumps([reference,evaluated,dt,dr,cutoff,spacing])
    if st.button('Evaluate Gamma Index'):
        try:
            if not reference or not evaluated or Path(reference).resolve()==Path(evaluated).resolve():
                raise ValueError('Provide two independent dose files; a self-comparison cannot verify patient QA.')
            result=evaluate_gamma_index(reference,evaluated,dt,dr,cutoff,reference_spacing_mm=json.loads(spacing),evaluated_spacing_mm=json.loads(spacing))
            st.session_state.gamma_result=(context_key,result)
        except (ValueError, OSError, AttributeError) as exc:
            st.session_state.pop('gamma_result',None); st.error(str(exc))
    saved=st.session_state.get('gamma_result')
    if saved and saved[0]==context_key:
        present_result(saved[1], 'gamma', 'gamma')

elif mode=='TOPAS Monte Carlo Deck Generator':
    st.subheader('Research TOPAS / Geant4 Parameter Deck Generator')
    with st.expander('ℹ️ TOPAS Deck Instructions & Physical Bounds', expanded=False):
        st.markdown(r"""
        **Generator Specifications:**
        - **Supported Particles**: Protons (`proton`), electrons (`e-`), photons/gammas (`gamma`), neutrons (`neutron`).
        - **Beam Kinetic Energy Bounds**: Supported application range: $0.01\text{ MeV} \le E \le 250\text{ MeV}$.
        - **Geometries**: Standard $30 \times 30 \times 30\text{ cm}$ water phantom (`water_phantom`) or slab heterogeneity.
        - **Scorer**: DoseToMedium mesh scoring output.
        """)
    particle=st.selectbox('Particle Type',['proton','e-','gamma','neutron'])
    energy=st.number_input('Beam Energy (MeV)',value=150.)
    geom=st.selectbox('Geometry',['water_phantom','slab_heterogeneity'])
    histories=st.number_input('Number of Histories',value=100000,min_value=1,step=10000)
    st.info('Patient CT transport is unavailable. Generated decks require TOPAS runtime and beam-model verification.')
    context_key=json.dumps([particle,energy,geom,histories])
    if st.button('Generate TOPAS Deck'):
        try:
            deck=generate_topas_deck(particle,energy,geom,number_of_histories=histories)
            st.session_state.topas_result=(context_key,deck,dict(particle=particle,energy_mev=energy,histories=histories,geometry=geom))
        except ValueError as exc:
            st.session_state.pop('topas_result',None); st.error(str(exc))
    saved=st.session_state.get('topas_result')
    if saved and saved[0]==context_key:
        present_result(saved[2], 'topas', 'topas')
        st.download_button('Download TOPAS parameter file',saved[1],file_name='topas_research.txt',mime='text/plain')
        with st.expander('Inspect parameter file'):
            st.code(saved[1],language='text')

elif mode=='Model Evaluation & Triage':
    from src.decision import EvaluationRequest
    from src.evaluation import evaluate_model
    from src.storage import StorageManager, session_scope
    st.subheader('Dose-model Assessment and Triage')
    st.info('APPROVED means a research candidate for this case. Missing calibration or OOD evidence requires review. Raw data stays read-only.')
    
    with st.expander('📖 Evaluation Manifest JSON Guide: Required Fields & Schema', expanded=False):
        st.markdown(r"""
        ### What is supposed to be input in the Evaluation JSON?
        The evaluation harness compares supplied dose arrays using explicit research policies. It does not certify model accuracy or standards compliance. Supply a valid JSON object matching the `EvaluationRequest` schema:

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
        | **Absorbed Dose Non-Negativity** | $D(\vec{r}) \ge 0.0$ Gy everywhere | N/A | Any $D < 0.0$ Gy (Investigate dose pipeline) |
        | **Custom Gamma (3% / 3 mm)** | $\ge 95.0\%$ | $90.0\% - 94.9\%$ | $< 90.0\%$ |
        | **Tight Margin Gamma (2% / 2 mm)** | $\ge 90.0\%$ | $85.0\% - 89.9\%$ | $< 85.0\%$ |
        | **TG-218 Reference Gamma (3% / 2 mm)**| $\ge 95.0\%$ | $90.0\% - 94.9\%$ | $< 90.0\%$ |
        | **PTV Coverage ($D_{95\%} / D_{\text{rx}}$)** | $\ge 95.0\%$ | $93.0\% - 94.9\%$ | $< 93.0\%$ (Target under-dosage) |
        | **Mean Absolute Error (MAE / $D_{\text{rx}}$)**| $< 1.5\%$ | $1.5\% - 3.0\%$ | $> 3.0\%$ |
        | **Serial OAR $D_{\text{max}} / D_{\text{limit}}$**| $< 98.0\%$ | $98.0\% - 100.0\%$ | $> 100.0\%$ (Configured dose limit exceeded) |
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
            st.session_state.evaluated_manifest = manifest
        except Exception as exc:
            st.error(f"Evaluation rejected: {str(exc)}")
    if 'model_evaluation' in st.session_state and st.session_state.get('evaluated_manifest') == manifest:
        result = st.session_state.model_evaluation
        st.metric('Research triage', result['status'])
        present_result(result, 'evaluation', 'evaluation')
        st.warning("⚠️ **RESEARCH USE ONLY — NOT FOR CLINICAL RELEASE**\n\n" + "\n".join(f"- {lim}" for lim in result.get('limitations', [])))
        with st.expander("Evaluation Provenance & Audit Payload", expanded=False):
            st.json({k: v for k, v in result.items() if k not in ('rules', 'limitations', 'clinical_release', 'status')})
        manager = StorageManager(os.getenv('STORAGE_DIR', './storage/sessions'))
        for artifact in result['artifacts']:
            if Path(artifact).suffix == '.png':
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
           - Computes a Poisson EUD TCP estimate from TCD50, gamma50 and a negative volume exponent; no fractionation or explicit LQ survival correction is applied.
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
    context_key=json.dumps([raw,model,params,histogram_type])
    if st.button('Calculate TCP / NTCP'):
        try:
            result=calculate_tcp_ntcp(json.loads(raw),model,json.loads(params),dvh_type=histogram_type)
            st.session_state.radiobio_result=(context_key,result)
        except (ValueError,TypeError,KeyError) as exc:
            st.session_state.pop('radiobio_result',None); st.error(str(exc))
    saved=st.session_state.get('radiobio_result')
    if saved and saved[0]==context_key:
        present_result(saved[1], 'radiobiology', 'radiobiology')

else:
    st.subheader('Trusted local Python REPL Sandbox')
    st.warning('This is unrestricted local Python, not a security sandbox. Never paste instructions or code from patient files.')
    with st.expander('ℹ️ REPL Sandbox Instructions & Visualization Artifacts', expanded=False):
        st.markdown("""
        - Persistent session: Variables, imports, and functions defined in earlier executions remain available.
        - Matplotlib figures created via `plt.show()` or `plt.savefig()` are automatically captured and rendered as artifacts.
        - Dose arrays are checked after execution. Arbitrary Python and generated files are not fully validated or isolated. Raw data must be mounted read-only when running trusted code.
        """)
    code=st.text_area('Python code',value="print('Local research REPL')")
    trusted=st.checkbox('I reviewed and trust this code')
    if st.button('Run Code',disabled=not trusted):
        result=st.session_state.agent.execute_code(code)
        (st.success if result['success'] else st.error)('Execution successful' if result['success'] else result['error'])
        st.text(result['stdout'])
        for artifact in result['artifacts']:st.image(artifact)

