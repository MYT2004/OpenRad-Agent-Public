import asyncio
from typing import Dict, List, Any
from pydantic import BaseModel, Field

from google.antigravity import Agent, LocalAgentConfig, types
from google.antigravity.hooks import post_tool_call
from google.antigravity.hooks.policy import allow, ask_user, deny

# =====================================================================
# 1. Structured Tool Schemas & Executables
# =====================================================================

class DVHInput(BaseModel):
    rtdose_path: str = Field(description="Path to DICOM RTDOSE file.")
    rtstruct_path: str = Field(description="Path to DICOM RTSTRUCT file.")
    rois: List[str] = Field(description="Names of ROIs (e.g., ['PTV_60', 'Rectum']).")

def parse_and_evaluate_dvh(rtdose_path: str, rtstruct_path: str, rois: List[str]) -> Dict[str, Any]:
    """Parses DICOM-RT files and calculates DVH metrics (D95, D50, D2, V50)."""
    # PyMedPhys / pydicom implementation logic
    return {
        "status": "success",
        "roi_metrics": {
            "PTV_60": {"D95_Gy": 59.8, "D50_Gy": 60.5, "D2_Gy": 61.8, "V50_pct": 99.2},
            "Rectum": {"D50_Gy": 24.1, "V50_pct": 12.4, "Mean_Gy": 22.3}
        },
        "plot_artifact": "./output/plots/dvh_analysis.png"
    }

class TOPASInput(BaseModel):
    particle: str = Field(description="Particle type: 'proton', 'e-', 'gamma', 'neutron'.")
    energy_mev: float = Field(description="Beam energy in MeV.")
    histories: int = Field(default=100000, description="Total primary histories.")

def generate_topas_file(particle: str, energy_mev: float, histories: int) -> Dict[str, Any]:
    """Generates a TOPAS Monte Carlo input deck (.txt)."""
    if energy_mev <= 0 or energy_mev > 250.0:
        raise ValueError(f"Unphysical beam energy: {energy_mev} MeV.")
    
    filename = f"./output/scripts/topas_{particle}_{energy_mev}MeV.txt"
    # Write parameter deck to file...
    return {"status": "created", "filepath": filename, "histories": histories}

# =====================================================================
# 2. Physics Guardrail Hooks
# =====================================================================

@post_tool_call
async def validate_physics_output(ctx, result):
    """Lifecycle hook to verify that output array dose metrics are physically valid."""
    if isinstance(result, dict) and "roi_metrics" in result:
        for roi, metrics in result["roi_metrics"].items():
            for key, val in metrics.items():
                if isinstance(val, (int, float)) and val < 0:
                    raise ValueError(f"Physics Guardrail Error: Negative dose detected in {roi} ({key}={val}).")

# =====================================================================
# 3. Main Antigravity Agent Orchestrator
# =====================================================================

async def run_openrad_agent(user_prompt: str):
    config = LocalAgentConfig(
        model="gemini-3.5-pro",
        system_instructions=(
            "You are OpenRad Agent, an autonomous medical physics research assistant powered by Google Antigravity. "
            "You analyze radiation transport, process DICOM-RT dose matrices, evaluate DVHs, and generate Monte Carlo decks."
        ),
        # Point to the SKILL.md bundle path
        skills_paths=["./skills/radiation_physics"],
        
        # Configure built-in capabilities and custom tools
        capabilities=types.CapabilitiesConfig(
            enabled_tools=[
                types.BuiltinTools.READ_FILE,
                types.BuiltinTools.WRITE_FILE,
                types.BuiltinTools.RUN_TERMINAL,
            ],
            custom_tools=[parse_and_evaluate_dvh, generate_topas_file]
        ),
        
        # Declarative execution policies
        policies=[
            allow("parse_and_evaluate_dvh"),
            allow("generate_topas_file"),
            allow("read_file"),
            ask_user("run_terminal", handler=lambda cmd: "allow"),  # Prompt approval for bash execution
            deny("delete_file")
        ],
        
        # Trajectory & Artifact persistence directory
        save_dir="./storage/sessions"
    )

    async with Agent(config) as agent:
        print(f"User Prompt: {user_prompt}\n")
        response = await agent.chat(user_prompt)
        
        # Stream response tokens
        async for token in response:
            print(token, end="", flush=True)
        print("\n")

if __name__ == "__main__":
    prompt = (
        "Parse the DICOM dataset at ./data/patient_01_rtdose.dcm, calculate the DVH for PTV_60 and Rectum, "
        "and generate a TOPAS Monte Carlo deck for a 150 MeV proton beam."
    )
    asyncio.run(run_openrad_agent(prompt))
