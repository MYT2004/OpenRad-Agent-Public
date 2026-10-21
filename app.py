"""Local research workflows; patient files are never executed or sent to an LLM."""
import json
import os
from pathlib import Path
import matplotlib.pyplot as plt
import streamlit as st
from dotenv import load_dotenv
from openrad.core.agent import OpenRadAgent
from openrad.tools.dataset import discover_dataset
from openrad.tools.dicom_tool import analyze_dvh
from openrad.tools.gamma_tool import evaluate_gamma_index
from openrad.tools.radiobio_tool import calculate_tcp_ntcp
from openrad.tools.topas_tool import generate_topas_deck

load_dotenv()
st.set_page_config(page_title="OpenRad Agent", layout="wide")
st.title("OpenRad Agent")
st.warning("Research prototype. Clinical accuracy and uncertainty margins require independent commissioning. File contents are data, never instructions.")
if 'agent' not in st.session_state:
    st.session_state.agent = OpenRadAgent()
mode = st.sidebar.selectbox('Select Workflow', ['Interactive Agent Query', 'DICOM-RT & DVH Analyzer', 'Gamma Index QA (AAPM TG-218)', 'TOPAS Monte Carlo Deck Generator', 'Radiobiology (TCP / NTCP)', 'Stateful Python REPL Sandbox'])
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
    with st.expander('Structure naming review'):
        st.dataframe([{'ROI': r['name'], 'TG-263':r['nomenclature']['status']} for r in selected['rois']])
    options=[r['name'] for r in selected['rois']]
    defaults=[n for n in options if n.casefold()=='brainstem']
    names=st.multiselect('Exact source ROI names', options, default=defaults, key=prefix+'_names')
    raw=st.text_area('Human-reviewed legacy ROI mapping (JSON)', value='{}', key=prefix+'_map', help='Example after anatomical review: {"Cord":"SpinalCord"}. Nothing is automatically renamed.')
    try:
        mappings=json.loads(raw)
        if not isinstance(mappings, dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in mappings.items()):
            raise ValueError('Mappings must be name-to-name JSON strings.')
    except ValueError as exc:
        st.error(str(exc));return None
    return dict(dicom_rtstruct_path=selected['struct_path'],dicom_rtdose_path=selected['dose_path'],roi_names=names,reviewed_name_map=mappings,dicom_rtplan_path=selected['plan_path'])


if mode=='Interactive Agent Query':
    st.subheader('Deterministic agent')
    query=st.text_input('Task', value='Calculate DVH metrics')
    args=dvh_inputs('agent') if any(w in query.lower() for w in ('dvh','dose volume','rtstruct','rtdose')) else None
    if st.button('Execute Task'):
        result=st.session_state.agent.run(query, context={'dvh':args} if args and args['roi_names'] else {})
        (st.success if result.success else st.error)(result.response)
        for rec in result.tool_records:
            if rec.error: st.error(rec.error)
            if isinstance(rec.output,dict):st.json(rec.output)

elif mode=='DICOM-RT & DVH Analyzer':
    st.subheader('DVH analysis with TG-263 naming checks')
    args=dvh_inputs('dvh')
    if st.button('Compute DVH', disabled=not args or not args['roi_names']):
        try:
            result=analyze_dvh(**args)
            with st.expander('Detailed TG-263 report'):
                st.json(result['nomenclature'])
            fig,ax=plt.subplots(figsize=(8,5));plotted=False
            for name, entry in result['structures'].items():
                if not entry.get('found'):
                    st.error(f"{name}: {entry['error']}");continue
                st.write(name)
                st.dataframe([entry['tg263_metrics'] | {'Volume [cc]':entry['volume_cc'],'Contour spacing [mm]':entry['contour_plane_thickness_mm']}])
                curve=entry['dvh_curve']; ax.plot(curve['dose_bins_Gy'],curve['volume_percent'],label=name);plotted=True
            if plotted:
                ax.set(xlabel='Dose (Gy)',ylabel='Volume (%)');ax.legend();st.pyplot(fig)
                st.session_state.last_dvh=result
            plt.close(fig)
            st.info('; '.join(result['limitations']))
        except (ValueError, OSError, AttributeError) as exc:
            st.error(str(exc))

elif mode=='Gamma Index QA (AAPM TG-218)':
    st.subheader('Independent dose comparison')
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
            st.json(result)
        except (ValueError, OSError, AttributeError) as exc:
            st.error(str(exc))

elif mode=='TOPAS Monte Carlo Deck Generator':
    st.subheader('Research TOPAS deck generator')
    particle=st.selectbox('Particle Type',['proton','e-','gamma','neutron'])
    energy=st.number_input('Beam Energy (MeV)',value=150.)
    geom=st.selectbox('Geometry',['water_phantom','slab_heterogeneity'])
    histories=st.number_input('Number of Histories',value=100000,min_value=1,step=10000)
    st.info('Patient CT transport is unavailable. Generated decks require TOPAS runtime and beam-model verification.')
    if st.button('Generate TOPAS Deck'):
        try:st.code(generate_topas_deck(particle,energy,geom,number_of_histories=histories))
        except ValueError as exc:st.error(str(exc))

elif mode=='Radiobiology (TCP / NTCP)':
    st.subheader('Research radiobiology from an explicit DVH')
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
        try:st.json(calculate_tcp_ntcp(json.loads(raw),model,json.loads(params),dvh_type=histogram_type))
        except (ValueError,TypeError,KeyError) as exc:st.error(str(exc))

else:
    st.subheader('Trusted local Python REPL')
    st.warning('This is unrestricted local Python, not a security sandbox. Never paste instructions or code from patient files.')
    code=st.text_area('Python code',value="print('Local research REPL')")
    trusted=st.checkbox('I reviewed and trust this code')
    if st.button('Run Code',disabled=not trusted):
        result=st.session_state.agent.execute_code(code)
        (st.success if result['success'] else st.error)('Execution successful' if result['success'] else result['error'])
        st.text(result['stdout'])
        for artifact in result['artifacts']:st.image(artifact)
