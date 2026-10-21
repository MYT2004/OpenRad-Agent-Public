"""FastAPI REST & Streaming Gateway for OpenRad Agent.

Provides endpoints for autonomous agent execution, DVH analysis, Gamma QA,
TOPAS Monte Carlo deck generation, and session artifact retrieval.
"""

import os
import uuid
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from openrad.core.agent import OpenRadAgent
from openrad.storage.manager import StorageManager
from openrad.tools.dicom_tool import analyze_dvh, DVHAnalysisInput
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STORAGE_BASE = os.getenv("STORAGE_DIR", "./storage/sessions")
storage_mgr = StorageManager(base_dir=STORAGE_BASE)

# Ensure storage directory exists and mount for serving artifacts
os.makedirs(STORAGE_BASE, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=STORAGE_BASE), name="artifacts")

agent_instance = OpenRadAgent(artifact_dir=STORAGE_BASE)


# =====================================================================
# Request / Response Schemas
# =====================================================================

class AgentRunRequest(BaseModel):
    prompt: str = Field(..., example="Calculate DVH metrics for Cord, Brainstem, and PTV 69.96 Gy")
    session_id: Optional[str] = Field(default=None, description="Optional existing session ID to resume trajectory.")
    model: str = Field(default="gemini-3.5-pro", description="Model identifier.")


class AgentRunResponse(BaseModel):
    session_id: str
    status: str
    response_text: str
    artifacts: List[str]
    trajectory_log: str


class SessionStatusResponse(BaseModel):
    session_id: str
    created_at: str
    artifact_count: int
    artifacts: List[str]


# =====================================================================
# API Endpoints
# =====================================================================

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "openrad-agent",
        "version": "1.0.0",
        "framework": "Google Antigravity & OpenRad Core",
    }


@app.post("/api/v1/agent/run", response_model=AgentRunResponse)
async def run_agent(payload: AgentRunRequest):
    session_id = payload.session_id or str(uuid.uuid4())
    storage_mgr.initialize_session(session_id)

    try:
        result = agent_instance.run(payload.prompt)
        storage_mgr.save_trajectory(session_id, payload.prompt, result.response)
        artifacts = storage_mgr.list_artifacts(session_id)

        # Include direct artifacts if any
        all_artifacts = list(set(artifacts + result.artifacts))

        return AgentRunResponse(
            session_id=session_id,
            status="completed" if result.success else "failed",
            response_text=result.response,
            artifacts=all_artifacts,
            trajectory_log=f"/artifacts/{session_id}/trajectory.json",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/dvh/analyze")
async def run_dvh(payload: DVHAnalysisInput):
    try:
        results = analyze_dvh(
            dicom_rtstruct_path=payload.dicom_rtstruct_path,
            dicom_rtdose_path=payload.dicom_rtdose_path,
            roi_names=payload.roi_names,
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/gamma/evaluate")
async def run_gamma(payload: GammaEvaluationInput):
    try:
        results = evaluate_gamma_index(
            reference_dose_path=payload.reference_dose_path,
            evaluated_dose_path=payload.evaluated_dose_path,
            dose_tolerance_percent=payload.dose_tolerance_percent,
            distance_tolerance_mm=payload.distance_tolerance_mm,
            dose_threshold_percent=payload.dose_threshold_percent,
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/topas/generate")
async def run_topas(payload: TOPASGeneratorInput):
    try:
        deck = generate_topas_deck(
            particle_type=payload.particle_type,
            energy_MeV=payload.energy_MeV,
            geometry_type=payload.geometry_type,
            phantom_dimensions_cm=payload.phantom_dimensions_cm,
            number_of_histories=payload.number_of_histories,
        )
        return {"status": "success", "deck": deck}
    except BeamEnergyBoundsError as e:
        raise HTTPException(status_code=422, detail=f"Physics Guardrail Error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/radiobio/calculate")
async def run_radiobio(payload: RadiobiologyInput):
    try:
        results = calculate_tcp_ntcp(
            dvh_data=payload.dvh_data,
            model_type=payload.model_type,
            parameters=payload.parameters,
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/sessions/{session_id}", response_model=SessionStatusResponse)
async def get_session(session_id: str):
    if not storage_mgr.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")

    meta = storage_mgr.get_metadata(session_id)
    artifacts = storage_mgr.list_artifacts(session_id)

    return SessionStatusResponse(
        session_id=session_id,
        created_at=meta.get("created_at", "unknown"),
        artifact_count=len(artifacts),
        artifacts=artifacts,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
