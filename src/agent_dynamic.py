"""Bounded Gemini function calling. Patient files remain local; no clinical release."""
from __future__ import annotations

from src.operations import audited_operation
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from uuid import uuid4
from pydantic import BaseModel, Field
from src.case_verification import CaseVerificationRequest, verify_patient_case, ensure_case_output_separation
from src.tools import parse_and_evaluate_dvh, generate_topas_file
from src.storage import current_session
from openrad.tools.dataset import discover_dataset
from openrad.tools.gamma_tool import evaluate_gamma_index
from openrad.validation.physics_rules import PhysicsValidationEngine, PhysicsValidationError

RESEARCH_DISCLAIMER = '**RESEARCH USE ONLY — NOT FOR CLINICAL RELEASE.**'

def _json(value):
    return json.dumps(value, allow_nan=False)

def _error(code):
    return _json({'status': 'ERROR', 'error_code': code, 'clinical_release': False})

def tool_verify_case_intake(folder_path: str) -> str:
    try:
        manager, _ = current_session()
        ensure_case_output_separation(folder_path, manager.base_dir)
        result = verify_patient_case(CaseVerificationRequest(root=folder_path, case_id='copilot-case', check_pixels=True))
        findings = result.get('findings', [])
        return _json({'status': result['status'], 'clinical_release': False,
            'files_hashed': result.get('files_hashed'), 'counts': result.get('counts'),
            'blocking_findings': sum(f.get('severity') == 'BLOCK' for f in findings),
            'review_findings': sum(f.get('severity') == 'REVIEW' for f in findings),
            'finding_codes': sorted({f.get('code', 'UNSPECIFIED') for f in findings}),
            'verification_hash': result.get('verification_hash'),
            'follow_up_actions': result.get('human_report',{}).get('follow_up_actions',[])[:32],
            'local_artifacts': _local_artifacts(result)})
    except Exception:
        return _error('INTAKE_FAILED')

def _local_artifacts(result):
    manager, _ = current_session()
    sid = result.get('session_id')
    if not sid: return []
    return [str((Path(manager.get_artifacts_dir(sid))/Path(uri).name).resolve())
            for uri in result.get('artifacts',[]) if (Path(manager.get_artifacts_dir(sid))/Path(uri).name).is_file()]

def tool_compute_dvh_metrics(rtdose_path: str, rtstruct_path: str, rois: list[str], *, rtplan_path=None, reviewed_name_map=None) -> str:
    try:
        if not rois or len(rois) > 64 or any(not isinstance(r, str) or not r.strip() for r in rois):
            return _error('EXPLICIT_ROIS_REQUIRED')
        if Path(rtdose_path).is_dir():
            pairs = discover_dataset(rtdose_path)['dose_cases']
            if len(pairs) != 1 or pairs[0].get('blockers'):
                return _error('UNAMBIGUOUS_LINKED_COURSE_REQUIRED')
            pair = pairs[0]
            rtdose_path, rtstruct_path, rtplan_path = pair['dose_path'], pair['struct_path'], pair.get('plan_path')
        result = parse_and_evaluate_dvh(rtdose_path, rtstruct_path, rois, rtplan_path=rtplan_path, reviewed_name_map=reviewed_name_map)
        structures = result.get('structures', {})
        complete = all(structures.get(r, {}).get('found', False) for r in rois)
        fields = ('volume_cc', 'mean_dose_Gy', 'max_dose_Gy', 'D95_Gy', 'D50_Gy', 'D2_Gy', 'V50_percent', 'V50_cc')
        return _json({'status': 'COMPLETED' if complete else 'INCOMPLETE', 'clinical_release': False,
            'course_linkage_verified': result.get('course_linkage_verified', False),
            'structures': {r: {k: s.get(k) for k in fields} if s.get('found') else {'found': False} for r,s in structures.items()},
            'local_artifacts': _local_artifacts(result),
            'limitations': ['V50 is volume at 50 Gy; no prescription or organ tolerance assumed.', 'Clinical constraints require a reviewed fractionation-specific protocol.']})
    except PhysicsValidationError:
        return _json({'status':'PHYSICS_VIOLATION','error_code':'INVALID_DOSE_OR_GEOMETRY','clinical_release':False})
    except Exception:
        return _error('DVH_FAILED')

def tool_evaluate_tg218_gamma(reference_dose_path: str, evaluated_dose_path: str, criteria='3pct_2mm', *, reference_spacing_mm=None, evaluated_spacing_mm=None) -> str:
    policies = {'3pct_2mm': (3.,2.,95.,90.), '3pct_3mm': (3.,3.,95.,90.), '2pct_2mm': (2.,2.,90.,85.)}
    if criteria not in policies:
        return _error('UNKNOWN_GAMMA_CRITERIA')
    if Path(reference_dose_path).resolve() == Path(evaluated_dose_path).resolve():
        return _error('INDEPENDENT_REFERENCE_REQUIRED')
    try:
        dt, dr, passing, review = policies[criteria]
        result = evaluate_gamma_index(reference_dose_path, evaluated_dose_path, dose_tolerance_percent=dt,
            distance_tolerance_mm=dr, dose_threshold_percent=10., reference_spacing_mm=reference_spacing_mm, evaluated_spacing_mm=evaluated_spacing_mm)
        rate = result['passing_rate']
        if not math.isfinite(rate) or not 0 <= rate <= 100:
            return _error('INVALID_GAMMA_RATE')
        return _json({'status':'COMPLETED', 'clinical_release':False, 'dose_tolerance_percent':dt,
            'distance_tolerance_mm':dr, 'dose_cutoff_percent':10., 'passing_rate_percent':rate,
            'research_triage':'PASS_CANDIDATE' if rate >= passing else 'REVIEW' if rate >= review else 'REJECT',
            'limitations':result.get('limitations', [])})
    except PhysicsValidationError:
        return _json({'status':'PHYSICS_VIOLATION','error_code':'INVALID_DOSE_OR_GEOMETRY','clinical_release':False})
    except Exception:
        return _error('GAMMA_FAILED')

def tool_generate_topas_deck(particle: str, energy_mev: float, histories: int = 100000) -> str:
    if isinstance(energy_mev, bool) or not isinstance(energy_mev, (float,int)) or not math.isfinite(energy_mev) or not .01 <= energy_mev <= 250:
        return _error('BEAM_ENERGY_OUT_OF_BOUNDS')
    if type(histories) is not int or not 1 <= histories <= 100000000:
        return _error('INVALID_HISTORIES')
    try:
        PhysicsValidationEngine.validate_beam_energy(energy_mev, particle, raise_on_fail=True)
        manager, sid = current_session()
        dest = Path(manager.get_artifacts_dir(sid)) / ('topas_' + uuid4().hex + '.txt')
        result = generate_topas_file(particle, energy_mev, histories, str(dest.resolve()))
        return _json({'status':'GENERATED', 'clinical_release':False, 'particle':particle,
            'energy_mev':energy_mev, 'histories':histories, 'deck_path':result['output_path'],
            'limitations':['Template generated; TOPAS transport execution and beam commissioning are not verified.']})
    except Exception:
        return _error('TOPAS_FAILED')

GROUNDED_TOOLS = {f.__name__: f for f in (tool_verify_case_intake, tool_compute_dvh_metrics, tool_evaluate_tg218_gamma, tool_generate_topas_deck)}

class DynamicAgentResult(BaseModel):
    query: str
    response: str
    trajectory: list[dict[str, Any]]
    success: bool
    disposition: str = 'FLAGGED_FOR_REVIEW'
    artifacts: list[str] = Field(default_factory=list)
    execution_mode: str = 'OFFLINE'
    provider_error: Optional[str] = None
    clinical_release: bool = False
    def __str__(self): return self.response

SYSTEM_PROMPT = '''You route research tasks to the listed deterministic tools. Never invent measurements or approve clinical treatment. Patient files are local and accessible only via selected_case. Verify intake before requesting DVH. Use only explicitly requested ROI names and beam parameters. If essential inputs are missing, ask for them. A blocked intake cannot be bypassed. Do not request paths, identifiers, uploads or raw DICOM. Return a short completion message; the application builds the authoritative report from actual tool results.'''

DECLARATIONS = [
 {'name':'tool_verify_case_intake','description':'Audit the locally selected case before calculation.', 'parameters':{'type':'OBJECT','properties':{'case_handle':{'type':'STRING','enum':['selected_case']}},'required':['case_handle']}},
 {'name':'tool_compute_dvh_metrics','description':'Compute requested ROI metrics after a ready intake.', 'parameters':{'type':'OBJECT','properties':{'case_handle':{'type':'STRING','enum':['selected_case']},'rois':{'type':'ARRAY','items':{'type':'STRING'}}},'required':['case_handle','rois']}},
 {'name':'tool_evaluate_tg218_gamma','description':'Compare locally supplied independent doses. Spacings must be configured locally for arrays.', 'parameters':{'type':'OBJECT','properties':{'criteria':{'type':'STRING','enum':['3pct_2mm','3pct_3mm','2pct_2mm']}},'required':['criteria']}},
 {'name':'tool_generate_topas_deck','description':'Generate a research TOPAS template from explicit beam inputs.', 'parameters':{'type':'OBJECT','properties':{'particle':{'type':'STRING'},'energy_mev':{'type':'NUMBER'},'histories':{'type':'INTEGER'}},'required':['particle','energy_mev','histories']}}
]

class ProviderFailure(Exception): pass

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Credentials must never follow a redirect to another host.

def _open_request(req):
    return build_opener(_NoRedirect()).open(req, timeout=30)


def _generate(key, model, contents):
    if not re.fullmatch(r'gemini-[a-zA-Z0-9.\-]+', model): raise ProviderFailure('INVALID_MODEL')
    body = {'systemInstruction':{'parts':[{'text':SYSTEM_PROMPT}]},'contents':contents,
        'tools':[{'functionDeclarations':DECLARATIONS}], 'generationConfig':{'temperature':0.1,'maxOutputTokens':2048}}
    req = Request('https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',
        data=json.dumps(body).encode(), headers={'Content-Type':'application/json','x-goog-api-key':key},method='POST')
    for attempt in range(2):
        try:
            with _open_request(req) as stream:
                data = stream.read(1048577)
            if len(data) > 1048576: raise ProviderFailure('PROVIDER_RESPONSE_TOO_LARGE')
            return json.loads(data)
        except HTTPError as exc:
            code = exc.code
            if exc.fp is not None: exc.fp.close()
            if code in (502,503,504) and attempt == 0:
                time.sleep(1)
                continue
            raise ProviderFailure('PROVIDER_HTTP_'+str(code)) from None
        except ProviderFailure: raise
        except Exception: raise ProviderFailure('PROVIDER_UNAVAILABLE') from None



@audited_operation
def run_dynamic_agent(query: str, api_key=None, model=None, *, case_directory=None, gamma_paths=None, gamma_spacing=None) -> DynamicAgentResult:
    """Six rounds / twelve calls maximum. Only opaque handles and summaries reach Gemini.

    The caller must supply a de-identified query. Raw paths/identifiers must never be
    entered in the query; local context is supplied separately and never transmitted.
    Provider failures are explicit and never trigger a simulated successful run.
    """
    key = api_key or os.getenv('GEMINI_API_KEY')
    mode = 'LIVE' if key else 'OFFLINE'
    trajectory, artifacts = [], []
    intake_ready = False
    failure = None
    if not isinstance(query, str) or not query.strip() or len(query)>8000:
        query = ''; failure = 'INVALID_QUERY'
    # Do not transmit path-bearing text or credentials, even if accidentally pasted.
    if key and key in query: failure = 'CREDENTIAL_IN_QUERY'
    if re.search(r'(?:/Users/|data/raw/|[A-Za-z]:\\|\.dcm\b|HNSCC-\d)', query): failure = 'USE_LOCAL_CONTEXT_FIELDS'

    def execute(name, args):
        nonlocal intake_ready
        declaration = next((d for d in DECLARATIONS if d['name']==name), None)
        if not declaration or not isinstance(args, dict): return json.loads(_error('UNKNOWN_TOOL_OR_ARGUMENTS'))
        schema = declaration['parameters']
        if set(args)-set(schema['properties']) or set(schema['required'])-set(args): return json.loads(_error('INVALID_TOOL_ARGUMENTS'))
        if name in ('tool_verify_case_intake','tool_compute_dvh_metrics'):
            if args.get('case_handle') != 'selected_case' or not case_directory: return json.loads(_error('LOCAL_CASE_REQUIRED'))
            if name=='tool_verify_case_intake':
                out=json.loads(tool_verify_case_intake(case_directory))
                intake_ready = out['status']=='READY_FOR_RESEARCH_ANALYSIS'
                return out
            if not intake_ready: return json.loads(_error('INTAKE_NOT_READY'))
            if not isinstance(args['rois'], list): return json.loads(_error('INVALID_ROIS'))
            if any(not isinstance(r,str) or not re.search(r'(?<!\w)'+re.escape(r)+r'(?!\w)',query,re.I) for r in args['rois']):
                return json.loads(_error('ROI_NOT_EXPLICITLY_REQUESTED'))
            return json.loads(tool_compute_dvh_metrics(case_directory, case_directory,args['rois']))
        if name=='tool_evaluate_tg218_gamma':
            if not gamma_paths or len(gamma_paths)!=2: return json.loads(_error('LOCAL_REFERENCE_PAIR_REQUIRED'))
            spacing = gamma_spacing or (None,None)
            return json.loads(tool_evaluate_tg218_gamma(*gamma_paths, **args, reference_spacing_mm=spacing[0],evaluated_spacing_mm=spacing[1]))
        requested = re.search(r'([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*MeV',query,re.I)
        if not requested or args.get('energy_mev') != float(requested.group(1)):
            return json.loads(_error('EXPLICIT_ENERGY_MISMATCH'))
        requested_histories=re.search(r'(\d+)\s+histories\b',query,re.I)
        expected_histories=int(requested_histories.group(1)) if requested_histories else 100000
        if args.get('histories') != expected_histories:
            return json.loads(_error('EXPLICIT_HISTORY_MISMATCH'))
        particles={'proton':r'\bprotons?\b', 'e-':r'\belectrons?\b|\be-', 'gamma':r'\b(?:gamma|photons?)\b', 'neutron':r'\bneutrons?\b'}
        if args.get('particle') not in particles or not re.search(particles[args['particle']],query,re.I):
            return json.loads(_error('EXPLICIT_PARTICLE_REQUIRED'))
        return json.loads(tool_generate_topas_deck(**args))

    def record(name,args):
        try: out=execute(name,args)
        except Exception: out=json.loads(_error('TOOL_EXECUTION_FAILED'))
        artifacts.extend(out.pop('local_artifacts', []))
        path=out.pop('deck_path',None)
        if path: artifacts.append(path)
        trajectory.append({'step':len(trajectory)+1, 'thought':'Executed allowlisted local tool; observation below.',
            'tool_name':name if name in GROUNDED_TOOLS else 'UNKNOWN_TOOL', 'arguments':args if name in GROUNDED_TOOLS else {}, 'observation':_json(out)})
        return out

    if not failure and key:
        contents=[{'role':'user','parts':[{'text':query}]}]
        try:
            for _ in range(6):
                response=_generate(key, model or os.getenv('GEMINI_MODEL','gemini-3.8-flash'),contents)
                content=response.get('candidates',[{}])[0].get('content',{})
                parts=content.get('parts',[])
                calls=[p['functionCall'] for p in parts if 'functionCall' in p]
                if not calls: break
                if len(trajectory)+len(calls)>12: raise ProviderFailure('TOOL_CALL_LIMIT')
                contents.append(content)  # Preserve opaque provider thought signatures, in memory only.
                replies=[]
                for call in calls:
                    name,args=call.get('name',''),call.get('args',{})
                    result=record(name,args)
                    reply={'name':name,'response':result}
                    if call.get('id'): reply['id']=call['id']
                    replies.append({'functionResponse':reply})
                contents.append({'role':'user','parts':replies})
            else: raise ProviderFailure('ROUND_LIMIT')
        except ProviderFailure as exc: failure=str(exc)
        except Exception: failure='INVALID_PROVIDER_RESPONSE'
    elif not failure:
        # Explicit offline mode is intake only; no invented parameters or metrics.
        if case_directory: record('tool_verify_case_intake',{'case_handle':'selected_case'})
        else: failure='API_KEY_OR_LOCAL_CASE_REQUIRED'
    required=set()
    if re.search(r'\bdvh\b',query,re.I): required.add('tool_compute_dvh_metrics')
    if re.search(r'\b(?:topas|deck)\b',query,re.I): required.add('tool_generate_topas_deck')
    if re.search(r'gamma (?:index|qa|comparison)',query,re.I): required.add('tool_evaluate_tg218_gamma')
    if not failure and required - {t['tool_name'] for t in trajectory}:
        failure='REQUESTED_ANALYSIS_NOT_PERFORMED'
    observations=[json.loads(t['observation']) for t in trajectory]
    success=bool(observations) and not failure and all(o['status'] in ('COMPLETED','GENERATED','READY_FOR_RESEARCH_ANALYSIS') for o in observations)
    rejected=any(o['status'] in ('BLOCKED','PHYSICS_VIOLATION') or o.get('research_triage')=='REJECT' or o.get('error_code')=='BEAM_ENERGY_OUT_OF_BOUNDS' for o in observations)
    disposition='REJECTED' if rejected else 'FLAGGED_FOR_REVIEW'
    lines=[RESEARCH_DISCLAIMER, '', 'Execution mode: '+mode, 'Research triage: '+disposition,
        'Clinical constraints and independent review remain required. No treatment or model approval is issued.']
    if failure: lines += ['', 'Execution stopped: '+failure+'. Correct configuration or inputs and run again.']
    if not observations: lines += ['', 'No deterministic evidence was produced. Supply explicit inputs and request a supported tool.']
    lines += ['', 'Next steps: review blocked findings in the local patient-file verifier; confirm anatomy, course, prescription and protocol before interpreting dosimetry. Compare results against an independent reference.']
    for step in trajectory:
        obs=json.loads(step['observation'])
        lines += ['', '### '+step['tool_name'].removeprefix('tool_').replace('_',' ').title(), '', '**Status: '+obs['status']+'**']
        if obs.get('error_code'): lines += ['Reason: '+obs['error_code']+' — '+obs['error_code'].replace('_',' ').lower()+'.']
        if 'files_hashed' in obs:
            lines += ['', '| Intake measure | Result |','|---|---:|']
            for field,label in [('files_hashed','Files checked'),('blocking_findings','Blocking findings'),('review_findings','Review findings')]:
                lines.append('| '+label+' | '+str(obs.get(field,'Not evaluated'))+' |')
        if 'structures' in obs:
            lines += ['', '| Structure | Volume (cc) | Mean (Gy) | D95 (Gy) | D50 (Gy) | D2 (Gy) | V50Gy (%) | Voxel Dmax (Gy) |', '|---|---:|---:|---:|---:|---:|---:|---:|']
            for name,metrics in obs['structures'].items():
                values=[metrics.get(k) for k in ('volume_cc','mean_dose_Gy','D95_Gy','D50_Gy','D2_Gy','V50_percent','max_dose_Gy')]
                lines.append('| '+name.replace('|',' ')+' | '+' | '.join('Not evaluated' if v is None else format(v,'.3f') for v in values)+' |')
        if 'passing_rate_percent' in obs:
            lines += [f"Gamma passing: {obs['passing_rate_percent']:.2f}% at {obs['dose_tolerance_percent']}% / {obs['distance_tolerance_mm']} mm; {obs['dose_cutoff_percent']}% cutoff. Research band: {obs['research_triage']}."]
        if obs['status']=='GENERATED':
            lines += [f"TOPAS template generated: {obs['particle']}, {obs['energy_mev']} MeV, {obs['histories']} histories. Transport simulation has not been executed."]
        lines += ['- '+action for action in obs.get('follow_up_actions',[])]
        lines += ['- '+limit for limit in obs.get('limitations',[])]

    return DynamicAgentResult(query='[local research request]',response='\n'.join(lines),trajectory=trajectory,
        success=success,disposition=disposition,artifacts=artifacts,execution_mode=mode,provider_error=failure)
