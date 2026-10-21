"""Orchestrator and Execution Loop for OpenRad Agent.

Coordinates task decomposition, tool routing, stateful REPL execution,
physics validation guardrails, and autonomous self-correction loops.
"""

import json
import os
from src.reports import build_report, markdown
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

from openrad.core.prompts import OPENRAD_SYSTEM_PROMPT
from openrad.sandbox.repl import StatefulPythonREPL, REPLExecutionResult
from openrad.tools.dicom_tool import analyze_dvh, DVHAnalysisInput
from openrad.tools.gamma_tool import evaluate_gamma_index, GammaEvaluationInput
from openrad.tools.radiobio_tool import calculate_tcp_ntcp, RadiobiologyInput
from openrad.tools.topas_tool import generate_topas_deck, TOPASGeneratorInput
from openrad.validation.physics_rules import (
    PhysicsValidationEngine,
    ValidationResult,
    PhysicsValidationError,
)


@dataclass
class ToolExecutionRecord:
    """Record of a tool invocation, arguments, result, and physics validation outcome."""
    tool_name: str
    arguments: Dict[str, Any]
    output: Any
    physics_passed: bool
    validation_detail: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class AgentExecutionResult:
    """Final output from OpenRad Agent execution."""
    task: str
    response: str
    tool_records: List[ToolExecutionRecord] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    self_correction_attempts: int = 0
    success: bool = True
    error: Optional[str] = None


class OpenRadAgent:
    """Autonomous Medical Physics & Radiotherapy Orchestration Agent."""

    def __init__(
        self,
        artifact_dir: Optional[str] = None,
        llm_client: Optional[Any] = None,
        model_name: str = "gpt-4o",
    ):
        if artifact_dir is None:
            from src.storage import current_session
            manager, session_id = current_session()
            artifact_dir = manager.get_artifacts_dir(session_id)
        from src.readonly import assert_output_path
        self.artifact_dir = str(assert_output_path(artifact_dir))
        os.makedirs(self.artifact_dir, exist_ok=True)

        self.repl = StatefulPythonREPL(artifact_dir=self.artifact_dir)
        self.validation_engine = PhysicsValidationEngine()
        self.llm_client = llm_client
        self.model_name = model_name
        self.system_prompt = OPENRAD_SYSTEM_PROMPT
        self.history: List[Dict[str, Any]] = []

        # Tool registry with typed JSON schemas
        from src.tools import evaluate_dvh_tool
        self.tools = {
            "analyze_dvh": evaluate_dvh_tool,
            "evaluate_gamma_index": evaluate_gamma_index,
            "generate_topas_deck": generate_topas_deck,
            "calculate_tcp_ntcp": calculate_tcp_ntcp,
            "execute_python_repl": self.execute_code,
        }

    def execute_code(self, code: str) -> Dict[str, Any]:
        """Wrapper for Stateful Python REPL execution."""
        res: REPLExecutionResult = self.repl.execute(code)
        return res.to_dict()

    def dispatch_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> ToolExecutionRecord:
        """Invokes a deterministic tool and routes its output through Physics Validation."""
        if tool_name not in self.tools:
            return ToolExecutionRecord(
                tool_name=tool_name,
                arguments=arguments,
                output=None,
                physics_passed=False,
                error=f"Tool '{tool_name}' not recognized in tool registry.",
            )

        fn = self.tools[tool_name]
        try:
            output = fn(**arguments)
            # Inspect output with physics validation
            physics_passed = True
            val_detail = None

            if tool_name == "evaluate_gamma_index":
                v = self.validation_engine.validate_gamma_index(
                    pass_rate=output.get("passing_rate", 0.0),
                    average_gamma=output.get("average_gamma"),
                    max_gamma=output.get("max_gamma"),
                )
                physics_passed = v.passed
                val_detail = v.to_dict()
            elif tool_name == "calculate_tcp_ntcp":
                v = self.validation_engine.validate_radiobiology(output)
                physics_passed = v.passed
                val_detail = v.to_dict()
            elif tool_name == "execute_python_repl":
                if output.get("physics_validation"):
                    val_detail = output["physics_validation"]
                    physics_passed = val_detail.get("passed", True)

            return ToolExecutionRecord(
                tool_name=tool_name,
                arguments=arguments,
                output=output,
                physics_passed=physics_passed,
                validation_detail=val_detail,
                error=val_detail.get("error_message") if val_detail and not physics_passed else None,
            )

        except PhysicsValidationError as pve:
            return ToolExecutionRecord(
                tool_name=tool_name,
                arguments=arguments,
                output=None,
                physics_passed=False,
                error=f"Physics Guardrail Violation: {str(pve)}",
                validation_detail={"rule_violation": str(type(pve).__name__), "message": str(pve)},
            )
        except Exception as e:
            return ToolExecutionRecord(
                tool_name=tool_name,
                arguments=arguments,
                output=None,
                physics_passed=False,
                error=f"Execution error: {str(e)}",
            )

    def run(self, task: str, max_retries: int = 3, context: Optional[Dict[str, Any]] = None) -> AgentExecutionResult:
        """Main execution loop for user queries.

        Orchestrates task analysis, tool invocation, physics validation,
        and self-correction loops.
        """
        context = context or {}
        tool_records: List[ToolExecutionRecord] = []
        artifacts: List[str] = []
        retries = 0

        # If LLM client is available, use LLM reasoning loop
        if self.llm_client is not None:
            return self._run_llm_loop(task, max_retries)

        # Autonomous Intent Router and Deterministic Physics Solver
        # Enables instant hackathon execution, CLI scripts, and offline testing
        task_lower = task.lower()

        # 1. DVH Analysis Intent
        if any(w in task_lower for w in ["dvh", "dose volume", "rtstruct", "rtdose"]):
            args = context.get("dvh")
            if not args:
                return AgentExecutionResult(task=task, response="Select a linked dose/structure dataset, exact ROI names and reviewed mappings in the DVH workflow. No sample patient is substituted.", success=False)
            record = self.dispatch_tool("analyze_dvh", args)
            tool_records.append(record)

            if record.physics_passed and record.output:
                res_dict = record.output
                nom = res_dict.get('nomenclature') or {}
                if isinstance(nom, dict):
                    std = nom.get('standard', 'AAPM TG-263')
                    ver = nom.get('vocabulary_version', '20170815')
                    n_eval = len(nom.get('structures', []))
                    nom_summary = f"{std} (v{ver}) — {n_eval} structure(s) evaluated"
                else:
                    nom_summary = str(nom)
                lines = [
                    "### OpenRad Agent: DVH Analysis Report",
                    "Research only. Interpret coverage and OAR metrics against the actual prescription and protocol.",
                    f"- **Dose Grid Dimensions**: {res_dict.get('dose_grid_shape')}",
                    f"- **Maximum Plan Dose**: {res_dict.get('max_dose_Gy')} Gy",
                    f"- **Numerical checks**: Nonnegative dose and supported geometry; clinical accuracy is unestablished.",
                    f"- **Nomenclature review**: {nom_summary}",
                    "\n#### Structure Metrics:",
                ]
                for s_name, s_data in res_dict.get("structures", {}).items():
                    if s_data.get("found"):
                        lines.append(
                            f"- **{s_data.get('structure_name', s_name)}**:\n"
                            f"  - Volume: {s_data.get('volume_cc')} cc\n"
                            f"  - Mean Dose: {s_data.get('mean_dose_Gy')} Gy | Max Dose: {s_data.get('max_dose_Gy')} Gy\n"
                            f"  - D95%[Gy]: {s_data.get('D95_Gy')} | D50%[Gy]: {s_data.get('D50_Gy')} | D2%[Gy]: {s_data.get('D2_Gy')}\n"
                            f"  - V50Gy[%]: {s_data.get('V50_percent')} | V50Gy[cc]: {s_data.get('V50_cc')}"
                        )
                    else:
                        lines.append(f"- **{s_name}**: {s_data.get('error', s_data.get('warning'))}")
                response = "\n".join(lines)
                return AgentExecutionResult(
                    task=task,
                    response=response,
                    tool_records=tool_records,
                    artifacts=artifacts,
                    success=all(v.get('found') and 'tg263_metrics' in v for v in res_dict.get('structures', {}).values()) and bool(res_dict.get('structures')),
                )
            return AgentExecutionResult(task=task, response=record.error or "DVH failed.", tool_records=tool_records, success=False)

        # 2. Gamma Index Evaluation Intent
        elif any(w in task_lower for w in ["gamma", "gamma index", "qa", "passing rate"]) and not any(w in task_lower for w in ["topas", "geant4", "deck", "monte carlo"]):
            # Check for parameters
            d_tol = 3.0
            dist_tol = 2.0
            cut_tol = 10.0
            m_dtol = re.search(r"(\d+(\.\d+)?)\s*%", task)
            if m_dtol:
                d_tol = float(m_dtol.group(1))
            m_dist = re.search(r"(\d+(\.\d+)?)\s*mm", task)
            if m_dist:
                dist_tol = float(m_dist.group(1))

            return AgentExecutionResult(
                task=task,
                response="Gamma QA requires explicit independent reference and evaluated dose inputs. Use the typed evaluate_gamma_index tool; the agent will not substitute a sample self-comparison.",
                success=False,
            )

        # 3. TOPAS Monte Carlo Intent
        elif any(w in task_lower for w in ["topas", "monte carlo", "geant4", "bragg peak", "deck"]):
            # Extract particle and energy
            particle = "proton"
            for p in ["proton", "e-", "electron", "gamma", "photon", "neutron"]:
                if p in task_lower:
                    particle = p
                    break

            energy = 150.0
            m_e = re.search(r"([+-]?\d+(\.\d+)?)\s*mev", task_lower)
            if m_e:
                energy = float(m_e.group(1))

            # Check self-correction loop if unphysical energy was asked
            record = self.dispatch_tool(
                "generate_topas_deck",
                {
                    "particle_type": particle,
                    "energy_MeV": energy,
                    "geometry_type": "ct_patient" if any(w in task_lower for w in ("ct_patient", "patient", "dicom")) else "water_phantom",
                    "phantom_dimensions_cm": [30.0, 30.0, 30.0],
                    "number_of_histories": 100000,
                },
            )
            tool_records.append(record)

            if record.physics_passed and record.output:
                from uuid import uuid4
                deck_path = os.path.join(self.artifact_dir, f"topas_{uuid4().hex}.txt")
                with open(deck_path, "w", encoding="utf-8") as f:
                    f.write(record.output)
                artifacts.append(deck_path)

                response = (
                    f"### OpenRad Agent: TOPAS Monte Carlo Input Deck Generated\n"
                    f"- **Particle Species**: {particle}\n"
                    f"- **Beam Energy**: {energy} MeV\n"
                    f"- **Geometry**: 30x30x30 cm Water Phantom (TsBox)\n"
                    f"- **Scorer**: DoseToMedium (CSV output, 60x60x120 mesh)\n"
                    f"- **Physics Validation**: Passed (0.01 <= E <= 250 MeV)\n"
                    f"- **Saved Deck Artifact**: `{deck_path}`"
                )
                return AgentExecutionResult(
                    task=task,
                    response=response,
                    tool_records=tool_records,
                    artifacts=artifacts,
                    self_correction_attempts=retries,
                    success=True,
                )

            return AgentExecutionResult(task=task, response=record.error or "TOPAS generation failed.", tool_records=tool_records, success=False)

        # 4. Radiobiological Modeling Intent (TCP / NTCP)
        elif any(w in task_lower for w in ["ntcp", "tcp", "lkb", "radiobiology", "eud"]):
            args = context.get("radiobiology")
            if not args:
                return AgentExecutionResult(task=task, response="Provide an explicit DVH and model parameters in the radiobiology workflow. No synthetic patient results are substituted.", success=False)
            record = self.dispatch_tool("calculate_tcp_ntcp", args)
            return AgentExecutionResult(task=task, response=markdown(build_report(record.output,'radiobiology')) if record.physics_passed else record.error, tool_records=[record], success=record.physics_passed)

        # 5. Model Verification & Clinical Follow-Up Actions Intent
        elif any(w in task_lower for w in ["verify", "evaluation", "validation", "safety audit", "model verification", "clinical report", "follow up", "follow-up"]):
            eval_args = context.get("evaluation") or context.get("validation")
            if not eval_args:
                return AgentExecutionResult(
                    task=task,
                    response="Provide model evaluation context (evaluated_dose, reference_dose, spacing_mm, structure_masks) in the evaluation workflow. The agent evaluates model safety without silent fallbacks.",
                    success=False,
                )
            from src.validation import verify_model_output, DecisionStatus
            report = verify_model_output(**eval_args)
            report_md = report.to_markdown()

            import uuid
            report_filename = f"report_{uuid.uuid4().hex}.md"
            report_path = os.path.join(self.artifact_dir, report_filename)
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report_md)
            artifacts.append(report_path)

            return AgentExecutionResult(
                task=task,
                response=report_md,
                tool_records=[
                    ToolExecutionRecord(
                        tool_name="verify_model_output",
                        arguments={k: v for k, v in eval_args.items() if not hasattr(v, "shape")},
                        output=report.model_dump(),
                        physics_passed=report.hard_physics_passed,
                        validation_detail=report.metrics,
                    )
                ],
                artifacts=artifacts,
                success=(report.status != DecisionStatus.REJECTED),
            )

        return AgentExecutionResult(task=task, response="Choose an explicit analysis workflow. Natural-language text and document contents are never executed as Python.", success=False)

    def _run_llm_loop(self, task: str, max_retries: int) -> AgentExecutionResult:
        """Runs multi-turn tool calling with LLM API client if provided."""
        # Stub for external LLM API client (OpenAI, Gemini, etc.)
        # Follows standard function calling schema with self-correction loop
        return AgentExecutionResult(task=task, response="External LLM tool calling is not implemented. Use deterministic workflows.", success=False)
