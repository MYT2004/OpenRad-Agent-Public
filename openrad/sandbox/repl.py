"""Stateful Python Execution REPL for OpenRad Agent.

Maintains execution state, variable persistence, array transformations,
dynamic plotting capture (matplotlib), and physics guardrails inspection.
"""

import ast
import io
import os
import sys
import traceback
from uuid import uuid4
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import numpy as np

from openrad.validation.physics_rules import (
    PhysicsValidationEngine,
    ValidationResult,
    DoseIntegrityError,
)


@dataclass
class REPLExecutionResult:
    """Encapsulates output, logs, generated artifacts, and physics checks from a REPL run."""
    success: bool
    stdout: str
    stderr: str
    result: Any = None
    artifacts: List[str] = field(default_factory=list)
    physics_validation: Optional[ValidationResult] = None
    error: Optional[str] = None
    trajectory: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "result": str(self.result) if self.result is not None else None,
            "artifacts": self.artifacts,
            "physics_validation": self.physics_validation.to_dict() if self.physics_validation else None,
            "error": self.error,
        }


class StatefulPythonREPL:
    """Persistent, isolated execution environment for medical physics computation."""

    def __init__(self, artifact_dir: Optional[str] = None):
        if artifact_dir is None:
            from src.storage import current_session
            manager, session_id = current_session()
            artifact_dir = manager.get_artifacts_dir(session_id)
        from src.readonly import assert_output_path
        self.artifact_dir = str(assert_output_path(artifact_dir))
        os.makedirs(self.artifact_dir, exist_ok=True)
        self.figure_counter = 0

        # Persistent namespace initialized with standard medical physics tools
        self.namespace: Dict[str, Any] = {}
        self._initialize_namespace()

    def _initialize_namespace(self) -> None:
        """Seeds the sandbox environment with essential libraries and OpenRad tools."""
        import matplotlib
        matplotlib.use("Agg")  # Non-interactive backend
        import matplotlib.pyplot as plt
        import scipy
        import pydicom
        from openrad.tools.dicom_tool import analyze_dvh
        from openrad.tools.gamma_tool import evaluate_gamma_index
        from openrad.tools.radiobio_tool import calculate_tcp_ntcp
        from openrad.tools.topas_tool import generate_topas_deck

        self.namespace.update({
            "np": np,
            "numpy": np,
            "scipy": scipy,
            "plt": plt,
            "pydicom": pydicom,
            "analyze_dvh": analyze_dvh,
            "evaluate_gamma_index": evaluate_gamma_index,
            "calculate_tcp_ntcp": calculate_tcp_ntcp,
            "generate_topas_deck": generate_topas_deck,
            "PhysicsValidationEngine": PhysicsValidationEngine,
            "__builtins__": __builtins__,
        })

    def reset(self) -> None:
        """Resets the REPL state to initial clean environment."""
        self.namespace.clear()
        self._initialize_namespace()
        self.figure_counter = 0

    def execute(self, code: str) -> REPLExecutionResult:
        """Executes a code block in the persistent namespace.

        Captures stdout, stderr, saves any created matplotlib figures,
        and runs physics validation guardrails on newly modified dose variables.
        """
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        redirected_stdout = io.StringIO()
        redirected_stderr = io.StringIO()

        stdout_text = ""
        stderr_text = ""
        eval_result = None
        artifacts: List[str] = []
        validation_res: Optional[ValidationResult] = None
        error_msg: Optional[str] = None
        success = True

        sys.stdout = redirected_stdout
        sys.stderr = redirected_stderr

        try:
            # Parse code to execute statements and evaluate the last line if it's an expression
            parsed = ast.parse(code)
            if parsed.body and isinstance(parsed.body[-1], ast.Expr):
                # Separate statements from the final expression
                stmts = parsed.body[:-1]
                expr = ast.Expression(parsed.body[-1].value)

                if stmts:
                    exec_mod = ast.Module(body=stmts, type_ignores=[])
                    exec(compile(exec_mod, "<repl>", "exec"), self.namespace)

                eval_result = eval(compile(expr, "<repl>", "eval"), self.namespace)
            else:
                exec(compile(code, "<repl>", "exec"), self.namespace)

        except Exception:
            success = False
            error_msg = traceback.format_exc()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            stdout_text = redirected_stdout.getvalue()
            stderr_text = redirected_stderr.getvalue()

        # Capture any matplotlib figures created during execution
        try:
            import matplotlib.pyplot as plt
            fig_nums = plt.get_fignums()
            if fig_nums:
                for f_num in fig_nums:
                    self.figure_counter += 1
                    fig = plt.figure(f_num)
                    art_path = os.path.join(
                        self.artifact_dir, f"plot_{uuid4().hex}.png"
                    )
                    fig.savefig(art_path, dpi=150, bbox_inches="tight")
                    artifacts.append(art_path)
                plt.close("all")
        except Exception as e:
            stderr_text += f"\nWarning capturing figures: {e}"

        # Physics Guardrail Check: Inspect dose arrays in namespace or returned result
        candidates = [(name, value) for name, value in self.namespace.items()
                      if 'dose' in name.lower() and isinstance(value, np.ndarray)]
        if isinstance(eval_result, np.ndarray):
            candidates.append(('returned_array', eval_result))
        for name, candidate in candidates:
            check = PhysicsValidationEngine.validate_dose_grid(candidate, raise_on_fail=False)
            validation_res = check
            if not check.passed:
                success = False
                error_msg = f'Physics Guardrail Violation in {name}: {check.error_message}\nAction Required: {check.remediation_suggestion}'
                break

        trajectory = {
            "code": code,
            "output_length": len(stdout_text),
            "artifacts_count": len(artifacts),
            "vars_in_scope": [k for k in self.namespace if not k.startswith("__")],
        }

        return REPLExecutionResult(
            success=success,
            stdout=stdout_text,
            stderr=stderr_text,
            result=eval_result,
            artifacts=artifacts,
            physics_validation=validation_res,
            error=error_msg,
            trajectory=trajectory,
        )
