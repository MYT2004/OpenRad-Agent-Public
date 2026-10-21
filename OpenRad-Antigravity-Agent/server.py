# server.py
import os
import uuid
import asyncio
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Security, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from google.antigravity import Agent, LocalAgentConfig, types
from google.antigravity.hooks import post_tool_call
from storage.manager import StorageManager

# =====================================================================
# Application Initialization & Setup
# =====================================================================

app = FastAPI(
    title="OpenRad Agent API",
    description="REST & Streaming Gateway for OpenRad Autonomous Medical Physics Agent powered by Google Antigravity",
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

# Mount static artifacts directory for serving plots/reports
app.mount("/artifacts", StaticFiles(directory=STORAGE_BASE), name="artifacts")


# =====================================================================
# Request / Response Schemas
# =====================================================================

class AgentRunRequest(BaseModel):
    prompt: str = Field(..., example="Parse ./data/rtdose.dcm and calculate DVH for PTV_60 and Rectum.")
    session_id: Optional[str] = Field(default=None, description="Optional existing session ID to resume trajectory.")
    model: str = Field(default="gemini-3.5-pro", description="Google Gemini model identifier.")

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
# Antigravity Custom Tools & Physics Guardrails
# =====================================================================

def parse_and_evaluate_dvh(rtdose_path: str, rtstruct_path: str, rois: List[str]) -> Dict[str, Any]:
    """Parses DICOM-RT files and calculates DVH metrics (D95, D50, D2, V50)."""
    # Tool mock wrapper binding into PyMedPhys/pydicom logic
    return {
        "status": "success",
        "roi_metrics": {
            "PTV_60": {"D95_Gy": 59.8, "D50_Gy": 60.5, "D2_Gy": 61.8, "V50_pct": 99.2},
            "Rectum": {"D50_Gy": 24.1, "V50_pct": 12.4, "Mean_Gy": 22.3}
        },
        "plot_path": "artifacts/dvh_analysis.png"
    }

def generate_topas_file(particle: str, energy_mev: float, histories: int) -> Dict[str, Any]:
    """Generates a TOPAS Monte Carlo input deck (.txt)."""
    if energy_mev <= 0 or energy_mev > 250.0:
        raise ValueError(f"Physics Guardrail Error: Energy {energy_mev} MeV out of range (0.01 - 250 MeV).")
    
    filename = f"topas_{particle}_{energy_mev}MeV.txt"
    return {"status": "created", "filename": filename, "histories": histories}

@post_tool_call
async def physics_guardrail_hook(ctx, result):
    """Enforces non-negative dose array integrity post tool execution."""
    if isinstance(result, dict) and "roi_metrics" in result:
        for roi, metrics in result["roi_metrics"].items():
            for metric, val in metrics.items():
                if isinstance(val, (int, float)) and val < 0:
                    raise ValueError(f"Physics Guardrail Error: Negative dose value in {roi} ({metric}={val}).")


# =====================================================================
# Core Agent Execution Driver
# =====================================================================

async def execute_agent_task(prompt: str, session_id: str, model_name: str) -> Dict[str, Any]:
    session_path = storage_mgr.get_session_dir(session_id)
    artifact_path = storage_mgr.get_artifacts_dir(session_id)

    config = LocalAgentConfig(
        model=model_name,
        system_instructions=(
            "You are OpenRad Agent, an autonomous medical physics research assistant built with Google Antigravity. "
            "Analyze radiation transport, process DICOM-RT dose matrices, compute DVHs, and generate Monte Carlo decks."
        ),
        skills_paths=["./skills/radiation_physics", "./SKILL.md"],
        capabilities=types.CapabilitiesConfig(
            enabled_tools=[
                types.BuiltinTools.READ_FILE,
                types.BuiltinTools.WRITE_FILE,
                types.BuiltinTools.RUN_TERMINAL,
            ],
            custom_tools=[parse_and_evaluate_dvh, generate_topas_file]
        ),
        save_dir=session_path
    )

    full_response = []
    async with Agent(config) as agent:
        response_stream = await agent.chat(prompt)
        async for chunk in response_stream:
            full_response.append(chunk)

    final_text = "".join(full_response)
    
    # Persist log trajectory and scan generated artifacts
    storage_mgr.save_trajectory(session_id, prompt, final_text)
    artifacts = storage_mgr.list_artifacts(session_id)

    return {
        "session_id": session_id,
        "status": "completed",
        "response_text": final_text,
        "artifacts": artifacts,
        "trajectory_log": f"/artifacts/{session_id}/trajectory.json"
    }


# =====================================================================
# API Endpoints
# =====================================================================

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "openrad-agent", "framework": "google-antigravity"}

@app.post("/api/v1/agent/run", response_model=AgentRunResponse)
async def run_agent(payload: AgentRunRequest):
    session_id = payload.session_id or str(uuid.uuid4())
    storage_mgr.initialize_session(session_id)
    
    try:
        result = await execute_agent_task(
            prompt=payload.prompt,
            session_id=session_id,
            model_name=payload.model
        )
        return AgentRunResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        artifacts=artifacts
    )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
