"""FastAPI REST & Streaming Gateway for OpenRad Agent.

Provides endpoints for autonomous agent execution, DVH analysis, Gamma QA,
TOPAS Monte Carlo deck generation, and session artifact retrieval.
"""

import os
import uuid
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path
import re
from pydantic import BaseModel, Field, AliasChoices

from openrad.core.agent import OpenRadAgent
from src.storage import StorageManager, session_scope
from src.tools import parse_and_evaluate_dvh, generate_topas_file
from src.config import skills_paths
from src.reports import attach_report
from src.decision import EvaluationRequest
from src.evaluation import evaluate_model
from src.governance import signed_review, verify_records

from openrad.tools.gamma_tool import evaluate_gamma_index, GammaEvaluationInput
from openrad.tools.radiobio_tool import calculate_tcp_ntcp, RadiobiologyInput
from openrad.tools.topas_tool import generate_topas_deck, TOPASGeneratorInput
from openrad.validation.physics_rules import PhysicsValidationEngine, BeamEnergyBoundsError

# =====================================================================
# Application Initialization & Setup
# =====================================================================

app = FastAPI(
    title="OpenRad Agent API",
    description="REST & Streaming Gateway for OpenRad Autonomous Medical Physics Agent (OSI Hackathon 2026)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:8501,http://127.0.0.1:8501").split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

STORAGE_BASE = os.getenv("STORAGE_DIR", "./storage/sessions")
storage_mgr = StorageManager(base_dir=STORAGE_BASE)

# =====================================================================
# Request / Response Schemas
# =====================================================================

class AgentRunRequest(BaseModel):
    prompt: str = Field(..., description="Explicit tool request; document content is not an instruction.")
    session_id: Optional[str] = Field(default=None, description="Optional existing session ID to resume trajectory.")
    context: Optional[Dict[str, Any]] = None
    model: str = Field(default="gemini-3.5-pro", description="Model identifier.")


class AgentRunResponse(BaseModel):
    session_id: str
    status: str
    response_text: str
    artifacts: List[str]
    trajectory_log: str


class DVHRequest(BaseModel):
    rtdose_path: str = Field(validation_alias=AliasChoices('rtdose_path', 'dicom_rtdose_path'))
    rtstruct_path: str = Field(validation_alias=AliasChoices('rtstruct_path', 'dicom_rtstruct_path'))
    rois: List[str] = Field(min_length=1, validation_alias=AliasChoices('rois', 'roi_names'))
    rtplan_path: Optional[str] = Field(default=None, validation_alias=AliasChoices('rtplan_path', 'dicom_rtplan_path'))
    reviewed_name_map: Optional[Dict[str,str]] = None
    session_id: Optional[str] = None


class TOPASRequest(BaseModel):
    particle: str = Field(validation_alias=AliasChoices('particle', 'particle_type'))
    energy_mev: float = Field(validation_alias=AliasChoices('energy_mev', 'energy_MeV'))
    histories: int = Field(default=100000, strict=True, gt=0, validation_alias=AliasChoices('histories','number_of_histories'))
    session_id: Optional[str] = None


class SessionStatusResponse(BaseModel):
    session_id: str
    created_at: str
    artifact_count: int
    artifacts: List[str]


# =====================================================================
# API Endpoints
# =====================================================================

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "openrad-agent",
        "version": "1.0.0",
        "skills_paths": skills_paths,
        "clinical_release": False,
    }


@app.post("/api/v1/agent/run", response_model=AgentRunResponse)
def run_agent(payload: AgentRunRequest):
    session_id = payload.session_id or str(uuid.uuid4())
    try:
        storage_mgr.initialize_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        session_agent = OpenRadAgent(artifact_dir=storage_mgr.get_artifacts_dir(session_id))
        with session_scope(storage_mgr, session_id):
            result = session_agent.run(payload.prompt, context=payload.context)
        storage_mgr.save_trajectory(session_id, "[request redacted]", "completed" if result.success else "failed")
        artifacts = storage_mgr.list_artifacts(session_id)

        # Include direct artifacts if any
        all_artifacts = artifacts

        return AgentRunResponse(
            session_id=session_id,
            status="completed" if result.success else "failed",
            response_text=result.response,
            artifacts=all_artifacts,
            trajectory_log="",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/dvh/analyze")
def run_dvh(payload: DVHRequest):
    try:
        with session_scope(storage_mgr, payload.session_id):
            return parse_and_evaluate_dvh(payload.rtdose_path, payload.rtstruct_path, payload.rois,
                rtplan_path=payload.rtplan_path, reviewed_name_map=payload.reviewed_name_map)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/v1/gamma/evaluate")
def run_gamma(payload: GammaEvaluationInput):
    try:
        results = evaluate_gamma_index(
            reference_dose_path=payload.reference_dose_path,
            evaluated_dose_path=payload.evaluated_dose_path,
            dose_tolerance_percent=payload.dose_tolerance_percent,
            distance_tolerance_mm=payload.distance_tolerance_mm,
            dose_threshold_percent=payload.dose_threshold_percent,
            reference_spacing_mm=payload.reference_spacing_mm,
            evaluated_spacing_mm=payload.evaluated_spacing_mm,
        )
        with session_scope(storage_mgr):
            return attach_report(results, 'gamma')
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/topas/generate")
def run_topas(payload: TOPASRequest):
    try:
        with session_scope(storage_mgr, payload.session_id) as session_id:
            filename = 'topas_' + uuid.uuid4().hex + '.txt'
            target = str(Path(storage_mgr.get_artifacts_dir(session_id))/filename)
            result = generate_topas_file(payload.particle, payload.energy_mev, payload.histories, target)
            result.pop('output_path', None)
            result.update(session_id=session_id)
            result['artifacts'].insert(0, f'/artifacts/{session_id}/artifacts/{filename}')
            return result
    except BeamEnergyBoundsError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/v1/radiobio/calculate")
def run_radiobio(payload: RadiobiologyInput):
    try:
        results = calculate_tcp_ntcp(
            dvh_data=payload.dvh_data,
            model_type=payload.model_type,
            parameters=payload.parameters,
            dvh_type=payload.dvh_type,
        )
        with session_scope(storage_mgr):
            return attach_report(results, 'radiobiology')
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/sessions/{session_id}", response_model=SessionStatusResponse)
def get_session(session_id: str):
    try:
        exists = storage_mgr.session_exists(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not exists:
        raise HTTPException(status_code=404, detail="Session not found.")

    meta = storage_mgr.get_metadata(session_id)
    artifacts = storage_mgr.list_artifacts(session_id)

    return SessionStatusResponse(
        session_id=session_id,
        created_at=meta.get("created_at", "unknown"),
        artifact_count=len(artifacts),
        artifacts=artifacts,
    )


@app.get('/artifacts/{session_id}/artifacts/{filename}')
def get_artifact(session_id: str, filename: str):
    if not re.fullmatch(r'(?:(?:dvh|decision|plot)_[a-f0-9]{32}\.png|topas_[a-f0-9]{32}\.txt|report_[a-f0-9]{32}\.md)', filename):
        raise HTTPException(status_code=404, detail='Artifact not found.')
    try:
        directory = Path(storage_mgr.get_artifacts_dir(session_id)).resolve()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    target = (directory/filename).resolve()
    if target.parent != directory or not target.is_file():
        raise HTTPException(status_code=404, detail='Artifact not found.')
    return FileResponse(target)


@app.post('/api/v1/evaluations')
def run_evaluation(payload: EvaluationRequest):
    try:
        with session_scope(storage_mgr):
            return evaluate_model(payload)
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail='Evaluation could not be committed; check inputs and server configuration.')


class SignedReviewRequest(BaseModel):
    payload: Dict[str, str]
    signature_b64: str


@app.post('/api/v1/sessions/{session_id}/reviews')
def review_evaluation(session_id: str, request: SignedReviewRequest):
    import json
    try:
        audit = Path(storage_mgr.get_session_dir(session_id)) / 'decisions.jsonl'
        records = [json.loads(line) for line in audit.read_text().splitlines() if line.strip()]
        verify_records(records)
        decision = next(r['event'] for r in records if r['event'].get('type') == 'evaluation'
                        and r['event'].get('decision_hash') == request.payload.get('decision_hash'))
        # Registry belongs to the server operator; it is never supplied by this request.
        keys = json.loads(os.getenv('OPENRAD_REVIEWER_KEYS', '{}'))
        return signed_review(audit, decision, request.payload, request.signature_b64, keys)
    except (ValueError, OSError, StopIteration):
        raise HTTPException(status_code=400, detail='Review rejected: check signature, trusted identity, decision, justification and nonce.')


def main():
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
