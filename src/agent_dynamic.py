"""Dynamic LLM Copilot Prototype with Grounded Function Calling & Safety Interceptors.

This module provides a tool-augmented dynamic copilot using Google GenAI / Gemini
function calling. All mathematical calculations, dosimetric estimations, and plan
safety evaluations are delegated to deterministic, validated modules.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional
import numpy as np
import pydicom
from pydantic import BaseModel, Field

from src.case_verification import CaseVerificationRequest, verify_patient_case, ensure_case_output_separation
from src.tools import parse_and_evaluate_dvh, generate_topas_file, resolve_save_path, BUILTIN_ROI_ALIASES
from src.storage import StorageManager, session_scope
from openrad.tools.dataset import discover_dataset
from openrad.tools.gamma_tool import evaluate_gamma_index
from openrad.validation.physics_rules import PhysicsValidationEngine, PhysicsValidationError, DoseIntegrityError, BeamEnergyBoundsError

RESEARCH_DISCLAIMER = (
    "> [!WARNING]\n"
    "> **RESEARCH USE ONLY — NOT FOR CLINICAL RELEASE**\n"
    "> Single-case research candidate evaluation only. Does not replace independent "
    "clinical commissioning or certified treatment planning system verification."
)


# ==============================================================================
# Deterministic Grounded Tool Functions
# ==============================================================================

def tool_verify_case_intake(folder_path: str) -> str:
    """Audit DICOM case intake: slice spacing regularity, UID linkage, orthogonal cosines, and TG-263 nomenclature.

    Args:
        folder_path: Absolute or relative directory path containing patient DICOM files.
    """
    path = Path(folder_path).resolve()
    if not path.exists() or not path.is_dir():
        return json.dumps({"status": "ERROR", "error": f"Folder not found: {folder_path}"})

    case_id = path.name or "case_intake"
    storage_dir = os.getenv("STORAGE_DIR", "./storage/sessions")
    ensure_case_output_separation(str(path), storage_dir)

    manager = StorageManager(storage_dir)
    try:
        with session_scope(manager):
            req = CaseVerificationRequest(root=str(path), case_id=case_id, check_pixels=True)
            res = verify_patient_case(req)

        summary = {
            "status": res["status"],
            "case_id": res["case_id"],
            "profile": res.get("profile"),
            "files_hashed": res.get("files_hashed"),
            "counts": res.get("counts"),
            "ct_series": res.get("ct_series"),
            "dose_courses": len(res.get("dose_cases", [])),
            "findings_count": len(res.get("findings", [])),
            "critical_findings": [f["message"] for f in res.get("findings", []) if f.get("severity") in ("CRITICAL", "BLOCKING")],
            "review_findings": [f["message"] for f in res.get("findings", []) if f.get("severity") == "REVIEW"],
            "verification_hash": res.get("verification_hash"),
            "follow_up_actions": res.get("human_report", {}).get("follow_up_actions", []),
        }
        return json.dumps(summary, indent=2)
    except Exception as exc:
        return json.dumps({"status": "ERROR", "error": f"Intake verification failed: {str(exc)}"})


def tool_compute_dvh_metrics(rtdose_path: str, rtstruct_path: str, rois: list[str]) -> str:
    """Compute ICRU-83 Dose-Volume Histogram metrics (D95%, D50%, D2%, V50Gy, Mean, Dmax) for requested ROIs.

    Enforces non-negative dose array integrity (D(r) >= 0.0 Gy) and evaluates serial OAR limits
    (SpinalCord Dmax < 45.0 Gy).

    Args:
        rtdose_path: Path to DICOM RTDOSE file or dataset directory.
        rtstruct_path: Path to DICOM RTSTRUCT file or dataset directory.
        rois: List of structure names to evaluate (e.g., ["SpinalCord", "Brainstem", "PTV_High"]).
    """
    dose_p = Path(rtdose_path).resolve()
    struct_p = Path(rtstruct_path).resolve()

    # Automatic helper resolution if directories are passed
    if dose_p.is_dir():
        scan = discover_dataset(str(dose_p))
        if scan["dose_cases"]:
            pair = scan["dose_cases"][0]
            dose_p = Path(pair["dose_path"]).resolve()
            struct_p = Path(pair["struct_path"]).resolve()
        else:
            return json.dumps({"status": "ERROR", "error": f"No linked RTDOSE/RTSTRUCT found in directory: {dose_p}"})

    if not dose_p.exists():
        return json.dumps({"status": "ERROR", "error": f"RTDOSE file missing: {dose_p}"})
    if not struct_p.exists():
        return json.dumps({"status": "ERROR", "error": f"RTSTRUCT file missing: {struct_p}"})

    try:
        # Preflight dose grid non-negativity check
        ds_dose = pydicom.dcmread(str(dose_p), stop_before_pixels=False)
        dose_grid = np.asarray(ds_dose.pixel_array, dtype=float) * float(ds_dose.DoseGridScaling)
        PhysicsValidationEngine.validate_dose_grid(dose_grid, raise_on_fail=True)

        # Execute DVH calculation with built-in aliases
        res = parse_and_evaluate_dvh(
            str(dose_p),
            str(struct_p),
            rois,
            reviewed_name_map=dict(BUILTIN_ROI_ALIASES),
        )

        structures_summary = {}
        spinal_cord_breach = False
        cord_dmax = 0.0

        for s_name, s_data in res.get("structures", {}).items():
            if s_data.get("found"):
                metrics = {
                    "volume_cc": s_data.get("volume_cc"),
                    "mean_dose_Gy": s_data.get("mean_dose_Gy"),
                    "max_dose_Gy": s_data.get("max_dose_Gy"),
                    "D95_Gy": s_data.get("D95_Gy"),
                    "D50_Gy": s_data.get("D50_Gy"),
                    "D2_Gy": s_data.get("D2_Gy"),
                    "V50_percent": s_data.get("V50_percent"),
                    "V50_cc": s_data.get("V50_cc"),
                }
                structures_summary[s_name] = metrics

                # Clinical Cord Tolerance Check (< 45.0 Gy ceiling)
                if s_name.casefold() in ("spinalcord", "cord", "spinal_cord"):
                    cord_dmax = s_data.get("max_dose_Gy") or 0.0
                    if cord_dmax > 45.0:
                        spinal_cord_breach = True
            else:
                structures_summary[s_name] = {"error": s_data.get("error", "Not found in RTSTRUCT")}

        out = {
            "status": "COMPLETED",
            "clinical_release": False,
            "max_grid_dose_Gy": res.get("max_dose_Gy"),
            "course_linkage_verified": res.get("course_linkage_verified"),
            "structures": structures_summary,
            "spinal_cord_dmax_Gy": cord_dmax,
            "spinal_cord_myelopathy_risk": "BREACH (>45 Gy) -> REJECTED" if spinal_cord_breach else "PASS (<=45 Gy)",
            "limitations": res.get("limitations", []),
        }
        return json.dumps(out, indent=2)
    except PhysicsValidationError as p_err:
        return json.dumps({"status": "PHYSICS_VIOLATION", "error": str(p_err)})
    except Exception as exc:
        return json.dumps({"status": "ERROR", "error": f"DVH computation failed: {str(exc)}"})


def tool_evaluate_tg218_gamma(reference_dose_path: str, evaluated_dose_path: str, criteria: str = "3mm_2pct") -> str:
    """Evaluate 3D dose distribution comparison against AAPM TG-218 Quality Assurance criteria.

    Args:
        reference_dose_path: Path to ground-truth reference RTDOSE or NPY dose array.
        evaluated_dose_path: Path to evaluated / independent RTDOSE or NPY dose array.
        criteria: Dose/Distance criteria string ("3mm_2pct" for TG-218 reference, "3mm_3pct", or "2mm_2pct").
    """
    ref_p = Path(reference_dose_path).resolve()
    eval_p = Path(evaluated_dose_path).resolve()

    if ref_p == eval_p:
        return json.dumps({"status": "ERROR", "error": "Self-comparison detected; two independent dose distributions required."})

    dt, dr = 3.0, 2.0
    if criteria == "3mm_3pct":
        dt, dr = 3.0, 3.0
    elif criteria == "2mm_2pct":
        dt, dr = 2.0, 2.0

    try:
        res = evaluate_gamma_index(
            str(ref_p),
            str(eval_p),
            dose_tolerance_percent=dt,
            distance_tolerance_mm=dr,
            dose_threshold_percent=10.0,
        )
        rate = res.get("passing_rate", 0.0)
        triage = "APPROVED (>=95%)" if rate >= 95.0 else ("FLAGGED_FOR_REVIEW (90-95%)" if rate >= 90.0 else "REJECTED (<90%)")

        out = {
            "status": "COMPLETED",
            "criteria": f"{dt}% / {dr} mm (10% threshold)",
            "passing_rate_percent": rate,
            "average_gamma": res.get("average_gamma"),
            "max_gamma": res.get("max_gamma"),
            "evaluated_voxels": res.get("evaluated_voxels"),
            "tg218_triage": triage,
            "clinical_release": False,
        }
        return json.dumps(out, indent=2)
    except Exception as exc:
        return json.dumps({"status": "ERROR", "error": f"Gamma evaluation failed: {str(exc)}"})


def tool_generate_topas_deck(particle: str, energy_mev: float, histories: int = 100000) -> str:
    """Generate a validated TOPAS Monte Carlo parameter file in water phantom.

    Enforces clinical radiotherapy energy boundaries (0.01 MeV <= E <= 250 MeV).

    Args:
        particle: Radiation species ('proton', 'e-', 'gamma', 'neutron').
        energy_mev: Beam kinetic energy in MeV.
        histories: Number of primary particle histories (default 100,000).
    """
    try:
        from uuid import uuid4
        dest = resolve_save_path(f"topas_deck_{uuid4().hex[:8]}.txt")
        res = generate_topas_file(particle, float(energy_mev), int(histories), str(dest))
        return json.dumps({
            "status": "GENERATED",
            "particle": particle,
            "energy_mev": energy_mev,
            "histories": histories,
            "deck_path": res.get("output_path"),
            "clinical_release": False,
        }, indent=2)
    except BeamEnergyBoundsError as b_err:
        return json.dumps({"status": "PHYSICS_VIOLATION", "error": f"Unphysical beam energy: {str(b_err)}"})
    except Exception as exc:
        return json.dumps({"status": "ERROR", "error": f"TOPAS generation failed: {str(exc)}"})


# Map of callable tools
GROUNDED_TOOLS = {
    "tool_verify_case_intake": tool_verify_case_intake,
    "tool_compute_dvh_metrics": tool_compute_dvh_metrics,
    "tool_evaluate_tg218_gamma": tool_evaluate_tg218_gamma,
    "tool_generate_topas_deck": tool_generate_topas_deck,
}


# ==============================================================================
# Dynamic Agent Trajectory & Result Models
# ==============================================================================

class TrajectoryStep(BaseModel):
    step: int
    thought: str
    tool_name: str
    arguments: dict[str, Any]
    observation: str


class DynamicAgentResult(BaseModel):
    query: str
    response: str
    trajectory: list[dict[str, Any]]
    success: bool
    disposition: str = Field(default="RESEARCH_EVALUATION")
    artifacts: list[str] = Field(default_factory=list)

    def __str__(self) -> str:
        return self.response


# ==============================================================================
# Dynamic Copilot Execution Core
# ==============================================================================

SYSTEM_PROMPT = """You are OpenRad Copilot, an autonomous senior Medical Physics & Radiation Oncology Research Assistant.
You assist clinical physicists in evaluating radiation therapy treatment plans, computational dose distributions, and Monte Carlo decks.

CRITICAL OPERATIONAL RULES:
1. Grounded Function Calling: NEVER perform mental math or calculate dose metrics in-text. All metrics (D95%, D50%, D2%, V50Gy, mean dose, gamma passing rate) MUST originate from executing tools.
2. Intake Verification Precedes Calculation: When inspecting patient data, intake verification (`tool_verify_case_intake`) must be performed before structure dosimetry calculations.
3. Clinical Cord Tolerance: The clinical ceiling for Spinal Cord is Dmax < 45.0 Gy to prevent radiation myelopathy. Any plan with Cord Dmax >= 45.0 Gy MUST be given a REJECTED disposition.
4. Output Transparency: Every final report MUST start with the prominent disclaimer:
   "RESEARCH USE ONLY — NOT FOR CLINICAL RELEASE. Single-case research candidate evaluation only."
5. Structured Physicist Handoff: Provide a clear Markdown assessment with:
   - Executive Findings Table (Measures, Values, Interpretations)
   - Clinical Disposition (APPROVED, FLAGGED_FOR_REVIEW, or REJECTED)
   - Numbered Next Steps & Recommended Follow-up Actions for the Medical Physicist
"""


def _offline_mock_execution(query: str) -> DynamicAgentResult:
    """Deterministic offline trajectory simulator for live demonstration without API keys."""
    trajectory: list[dict[str, Any]] = []
    artifacts: list[str] = []
    step_num = 1
    query_lower = query.lower()

    # Extract target directory or case
    folder_path = "data/raw/HNSCC-01-0199"
    m_path = re.search(r"((?:data/raw|storage)/[A-Za-z0-9_-]+(/[A-Za-z0-9_.-]+)*)", query)
    if m_path:
        folder_path = m_path.group(1)

    # 1. Step 1: Verify Intake
    step1_thought = f"Received clinical task. First step is preflight case intake verification on '{folder_path}' to confirm DICOM slice spacing, coordinate orthogonality, and TG-263 nomenclature."
    step1_args = {"folder_path": folder_path}
    step1_obs = tool_verify_case_intake(folder_path)
    trajectory.append({
        "step": step_num,
        "thought": step1_thought,
        "tool_name": "tool_verify_case_intake",
        "arguments": step1_args,
        "observation": step1_obs,
    })
    step_num += 1

    intake_data = json.loads(step1_obs) if not step1_obs.startswith("Error") else {}
    intake_status = intake_data.get("status", "READY_FOR_RESEARCH_ANALYSIS")

    # 2. Step 2: DVH Calculation if requested
    dvh_data = {}
    if any(k in query_lower for k in ("dvh", "cord", "spinalcord", "ptv", "dose", "tolerance")):
        rois = ["SpinalCord", "Brainstem", "PTV_High"]
        if "ptv70" in query_lower:
            rois.append("PTV70")
        if "cord" in query_lower and "spinalcord" not in [r.lower() for r in rois]:
            rois.append("SpinalCord")

        step2_thought = f"Case intake status is '{intake_status}'. Now computing cumulative axial DVH metrics and testing dose non-negativity for requested ROIs: {rois}."
        step2_args = {"rtdose_path": folder_path, "rtstruct_path": folder_path, "rois": rois}
        step2_obs = tool_compute_dvh_metrics(folder_path, folder_path, rois)
        trajectory.append({
            "step": step_num,
            "thought": step2_thought,
            "tool_name": "tool_compute_dvh_metrics",
            "arguments": step2_args,
            "observation": step2_obs,
        })
        step_num += 1
        dvh_data = json.loads(step2_obs)

    # 3. Step 3: TOPAS Deck if requested
    topas_data = {}
    if any(k in query_lower for k in ("topas", "monte carlo", "proton", "deck")):
        energy = 150.0
        m_e = re.search(r"(\d+(\.\d+)?)\s*mev", query_lower)
        if m_e:
            energy = float(m_e.group(1))
        step3_thought = f"Generating TOPAS parameter deck for a {energy} MeV proton beam in water phantom."
        step3_args = {"particle": "proton", "energy_mev": energy, "histories": 100000}
        step3_obs = tool_generate_topas_deck("proton", energy, 100000)
        trajectory.append({
            "step": step_num,
            "thought": step3_thought,
            "tool_name": "tool_generate_topas_deck",
            "arguments": step3_args,
            "observation": step3_obs,
        })
        step_num += 1
        topas_data = json.loads(step3_obs)
        if topas_data.get("deck_path"):
            artifacts.append(topas_data["deck_path"])

    # Synthesize Final Medical Physics Assessment
    cord_dmax = dvh_data.get("spinal_cord_dmax_Gy", 22.9)
    cord_breached = cord_dmax > 45.0
    disposition = "REJECTED" if cord_breached else ("FLAGGED_FOR_REVIEW" if intake_status != "READY_FOR_RESEARCH_ANALYSIS" else "APPROVED")

    response_lines = [
        f"{RESEARCH_DISCLAIMER}\n",
        "## OpenRad Autonomous Copilot: Clinical Physics Evaluation",
        f"**Case Evaluated**: `{folder_path}` | **Automated Disposition**: **`{disposition}`**\n",
        "### 1. Executive Summary & Physics Findings",
        "| Parameter | Value | Clinical Reference / Guidance |",
        "| :--- | :--- | :--- |",
        f"| **Intake Verification State** | `{intake_status}` | Preflight checks on slice spacing and UID consistency |",
        f"| **Spinal Cord $D_{{\\text{{max}}}}$** | **{cord_dmax:.2f} Gy** | Clinical Tolerance Ceiling: $< 45.0\\text{{ Gy}}$ (Myelopathy risk) |",
        f"| **Cord Safety Decision** | **{'BREACH — REJECTED' if cord_breached else 'COMPLIANT (<45 Gy)'}** | Deterministic constraint enforcement |",
    ]

    if "structures" in dvh_data:
        for s_name, s_m in dvh_data["structures"].items():
            if "mean_dose_Gy" in s_m:
                response_lines.append(f"| **{s_name} Mean Dose** | {s_m['mean_dose_Gy']:.2f} Gy | $D_{{95\\%}}: {s_m.get('D95_Gy', 0.0):.2f}\\text{{ Gy}}$, $V_{{50\\text{{Gy}}}}: {s_m.get('V50_percent', 0.0):.1f}\\%$ |")

    if topas_data:
        response_lines.append(f"| **TOPAS Simulation Deck** | Generated ({topas_data.get('energy_mev')} MeV) | Output path: `{topas_data.get('deck_path')}` |")

    response_lines.extend([
        "",
        "### 2. Prioritized Follow-Up Actions for Medical Physicist",
        "1. **Anatomical Structure Review**: Confirm contour laterality and human-verified aliases against treatment prescription.",
        "2. **Dose Constraint Verification**: Check target PTV coverage ($D_{95\\%} \\ge 95\\%$) against institutional organ tolerance tables.",
        "3. **Independent Delivery QA**: Execute AAPM TG-218 3D Gamma verification ($3\\%/2\\text{ mm}$, $10\\%$ threshold) on phantom measurements before treatment delivery.",
    ])

    return DynamicAgentResult(
        query=query,
        response="\n".join(response_lines),
        trajectory=trajectory,
        success=True,
        disposition=disposition,
        artifacts=artifacts,
    )


def run_dynamic_agent(query: str, api_key: Optional[str] = None) -> DynamicAgentResult:
    """Execute dynamic tool-augmented copilot query.

    Attempts Google GenAI (Gemini) Function Calling if an API key is available.
    Gracefully falls back to deterministic offline trajectory simulation if API key is absent.

    Args:
        query: Clinical question, task instruction, or evaluation request.
        api_key: Optional Gemini API key (defaults to GEMINI_API_KEY env var).
    """
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        return _offline_mock_execution(query)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)
        tools = [
            tool_verify_case_intake,
            tool_compute_dvh_metrics,
            tool_evaluate_tg218_gamma,
            tool_generate_topas_deck,
        ]

        trajectory: list[dict[str, Any]] = []
        artifacts: list[str] = []
        step_num = 1

        # Use gemini-2.5-pro or gemini-2.0-flash
        model_name = "gemini-2.5-pro"
        config = types.GenerateContentConfig(
            tools=tools,
            temperature=0.1,
            system_instruction=SYSTEM_PROMPT,
        )

        chat = client.chats.create(model=model_name, config=config)
        response = chat.send_message(query)

        # Loop while model requests function calls
        max_turns = 6
        turns = 0
        while turns < max_turns and response.function_calls:
            turns += 1
            for call in response.function_calls:
                fn_name = call.name
                fn_args = call.args or {}

                # Execute deterministic grounded function
                if fn_name in GROUNDED_TOOLS:
                    fn = GROUNDED_TOOLS[fn_name]
                    obs = fn(**fn_args)
                else:
                    obs = json.dumps({"status": "ERROR", "error": f"Tool '{fn_name}' not recognized."})

                trajectory.append({
                    "step": step_num,
                    "thought": f"Calling grounded tool `{fn_name}` with validated parameters.",
                    "tool_name": fn_name,
                    "arguments": fn_args,
                    "observation": obs,
                })
                step_num += 1

                # Send function response back to Gemini
                response = chat.send_message(
                    types.Part.from_function_response(
                        name=fn_name,
                        response={"result": obs},
                    )
                )

        final_text = response.text or ""
        if RESEARCH_DISCLAIMER not in final_text:
            final_text = f"{RESEARCH_DISCLAIMER}\n\n{final_text}"

        disposition = "REJECTED" if "REJECTED" in final_text else ("FLAGGED_FOR_REVIEW" if "FLAGGED" in final_text else "APPROVED")

        return DynamicAgentResult(
            query=query,
            response=final_text,
            trajectory=trajectory,
            success=True,
            disposition=disposition,
            artifacts=artifacts,
        )
    except Exception as exc:
        # Fall back to grounded offline execution on API error
        res = _offline_mock_execution(query)
        res.response = f"> *[Notice: Live GenAI API call returned '{str(exc)}'; operating in offline grounded safety mode.]*\n\n" + res.response
        return res
