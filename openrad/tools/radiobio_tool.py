"""Radiobiological Modeling Tool (TCP / NTCP Calculation) for OpenRad Agent.

Implements Lyman-Kutcher-Burman (LKB) NTCP and Poisson-LQ / Logistic TCP modeling
with generalized Equivalent Uniform Dose (EUD) and biological parameter guardrails.
"""

import math
from typing import Dict, List, Optional, Tuple
import numpy as np
from pydantic import BaseModel, Field
from scipy.special import erf

from openrad.validation.physics_rules import (
    PhysicsValidationEngine,
    RadiobiologyBoundsError,
)


class RadiobiologyInput(BaseModel):
    dvh_data: Dict[str, List[float]] = Field(description="Dose and volume bins extracted from DVH analysis.")
    model_type: str = Field(description="'LKB' (Lyman-Kutcher-Burman) or 'Poisson_LQ'.")
    parameters: Dict[str, float] = Field(
        description="Model constants: e.g., {'TD50': 55.0, 'm': 0.15, 'n': 0.25, 'alpha_beta': 3.0}."
    )


def _extract_diff_dvh(dvh_data: Dict[str, List[float]]) -> Tuple[np.ndarray, np.ndarray]:
    """Converts cumulative or differential DVH dictionary into differential volume fractions and doses."""
    # Find dose keys
    dose_key = next((k for k in dvh_data if "dose" in k.lower()), None)
    vol_key = next((k for k in dvh_data if "vol" in k.lower()), None)

    if not dose_key or not vol_key:
        keys = list(dvh_data.keys())
        if len(keys) >= 2:
            dose_key, vol_key = keys[0], keys[1]
        else:
            raise ValueError(f"DVH data dictionary must contain dose and volume lists. Got keys: {keys}")

    doses = np.asarray(dvh_data[dose_key], dtype=float)
    vols = np.asarray(dvh_data[vol_key], dtype=float)

    if len(doses) != len(vols) or len(doses) < 2:
        raise ValueError("Dose and volume arrays must have matching length >= 2.")

    PhysicsValidationEngine.validate_dose_grid(doses, raise_on_fail=True)
    if doses.ndim != 1 or vols.ndim != 1 or not np.isfinite(vols).all() or (vols < 0).any() or vols.sum() <= 0:
        raise RadiobiologyBoundsError("DVH volumes must be finite, non-negative, one-dimensional and nonempty.")
    if (np.diff(doses) <= 0).any():
        raise RadiobiologyBoundsError("Dose bins must be strictly increasing.")
    # Check if cumulative (monotonically decreasing or non-increasing volume)
    is_cumulative = bool(vols[0] > vols[-1])

    if is_cumulative:
        if (np.diff(vols) > 0).any() or vols[-1] != 0:
            raise RadiobiologyBoundsError("Cumulative DVH must decrease monotonically to zero; incomplete tails cannot be normalized.")
        # Normalize volumes to percentages [0, 100]
        max_v = float(np.max(vols))
        if max_v > 1.0:
            vol_pct = vols
        else:
            vol_pct = vols * 100.0

        # Calculate differential volume fractions
        diff_vol = np.abs(np.diff(vol_pct))
        total_vol = np.sum(diff_vol)
        if total_vol > 0:
            fracs = diff_vol / total_vol
        else:
            fracs = np.ones(len(diff_vol)) / len(diff_vol)

        # Midpoint doses
        mid_doses = 0.5 * (doses[:-1] + doses[1:])
        return mid_doses, fracs
    else:
        # Already differential
        total_vol = float(np.sum(vols))
        fracs = vols / total_vol if total_vol > 0 else np.ones(len(vols)) / len(vols)
        return doses, fracs


def calculate_tcp_ntcp(
    dvh_data: Dict[str, List[float]],
    model_type: str,
    parameters: Dict[str, float],
) -> Dict[str, float]:
    """Calculates Tumor Control Probability (TCP) or Normal Tissue Complication Probability (NTCP)

    using radiobiological parameters and equivalent uniform dose (EUD).
    """
    mid_doses, fracs = _extract_diff_dvh(dvh_data)
    m_type = model_type.strip().upper()

    # Parameter lookup helper (case insensitive)
    params_norm = {k.lower().replace("_", ""): float(v) for k, v in parameters.items()}

    if not all(np.isfinite(v) for v in params_norm.values()):
        raise RadiobiologyBoundsError("Model parameters must be finite.")

    if "LKB" in m_type or "LYMAN" in m_type:
        # Lyman-Kutcher-Burman (LKB) NTCP Model
        # Required: TD50 (or td50), m, n
        td50 = params_norm.get("td50") or params_norm.get("d50")
        m = params_norm.get("m")
        n = params_norm.get("n")
        ab = params_norm.get("alphabeta", 3.0)  # default 3 Gy for late-responding normal tissues

        if td50 is None or td50 <= 0:
            raise RadiobiologyBoundsError("LKB parameter 'TD50' must be provided and > 0 Gy.")
        if m is None or m <= 0:
            raise RadiobiologyBoundsError("LKB slope parameter 'm' must be provided and > 0.")
        if n is None or n <= 0:
            raise RadiobiologyBoundsError("LKB volume effect parameter 'n' must be provided and > 0.")

        # Generalized EUD: EUD = (sum(v_i * D_i^(1/n)))^n
        inv_n = 1.0 / n
        power_sum = float(np.sum(fracs * (mid_doses ** inv_n)))
        eud = power_sum ** n

        # Normalized variable t = (EUD - TD50) / (m * TD50)
        t = (eud - td50) / (m * td50)

        # Standard normal cumulative distribution function
        ntcp = float(0.5 * (1.0 + erf(t / math.sqrt(2.0))))
        ntcp = max(0.0, min(1.0, ntcp))

        res = {
            "model": "Lyman-Kutcher-Burman (LKB)",
            "EUD_Gy": round(eud, 2),
            "NTCP": round(ntcp, 4),
            "t_score": round(t, 3),
            "TD50_Gy": td50,
            "m_slope": m,
            "n_volume_effect": n,
        }

        PhysicsValidationEngine.validate_radiobiology(res, raise_on_fail=True)
        return res

    elif "POISSON" in m_type or "LQ" in m_type or "TCP" in m_type:
        # Poisson-LQ / Logistic TCP Model
        # Required: TCD50 (or TD50), gamma50 (or gamma_50)
        tcd50 = params_norm.get("tcd50") or params_norm.get("td50") or params_norm.get("d50", 65.0)
        gamma50 = params_norm.get("gamma50") or params_norm.get("gamma") or 2.0
        a_param = params_norm.get("a", -10.0)  # tumor volume effect exponent

        if tcd50 <= 0:
            raise RadiobiologyBoundsError("TCP parameter 'TCD50' must be > 0 Gy.")
        if gamma50 <= 0:
            raise RadiobiologyBoundsError("TCP slope parameter 'gamma_50' must be > 0.")

        if a_param >= 0:
            raise RadiobiologyBoundsError("Tumor EUD exponent a must be negative.")

        # Generalized EUD for tumor
        # Cold spots dominate tumor control -> negative exponent
        power_sum = float(np.sum(fracs * (np.maximum(mid_doses, 0.01) ** a_param)))
        eud = power_sum ** (1.0 / a_param)

        # Poisson TCP form: TCP = (0.5) ** exp((2 * gamma50 / ln2) * (1 - EUD / TCD50))
        exponent = (2.0 * gamma50 / math.log(2.0)) * (1.0 - (eud / tcd50))
        # Prevent numerical overflow
        clamped_exp = max(-50.0, min(50.0, exponent))
        tcp = float((0.5) ** math.exp(clamped_exp))
        tcp = max(0.0, min(1.0, tcp))

        res = {
            "model": "Poisson-LQ TCP",
            "EUD_Gy": round(eud, 2),
            "TCP": round(tcp, 4),
            "TCD50_Gy": tcd50,
            "gamma50": gamma50,
        }

        PhysicsValidationEngine.validate_radiobiology(res, raise_on_fail=True)
        return res

    else:
        raise ValueError(f"Unknown model_type '{model_type}'. Choose 'LKB' or 'Poisson_LQ'.")
