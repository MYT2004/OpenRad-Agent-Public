"""Radiobiological Modeling Tool (TCP / NTCP Calculation) for OpenRad Agent.

Implements Lyman-Kutcher-Burman (LKB) NTCP and Poisson-LQ / Logistic TCP modeling
with generalized Equivalent Uniform Dose (EUD) and biological parameter guardrails.
"""

from src.operations import audited_operation

import math
from typing import Dict, List, Optional, Tuple
import numpy as np
from pydantic import BaseModel, Field
from scipy.special import erf, logsumexp

from openrad.validation.physics_rules import (
    PhysicsValidationEngine,
    RadiobiologyBoundsError,
)


class RadiobiologyInput(BaseModel):
    dvh_data: Dict[str, List[float]] = Field(description="Dose and volume bins extracted from DVH analysis.")
    model_type: str = Field(description="'LKB' (Lyman-Kutcher-Burman) or 'Poisson_LQ'.")
    dvh_type: str = "cumulative"
    parameters: Dict[str, float] = Field(
        description="Model constants: e.g., {'TD50': 55.0, 'm': 0.15, 'n': 0.25, 'alpha_beta': 3.0}."
    )


def _extract_diff_dvh(dvh_data, dvh_type="cumulative"):
    """Explicit Gy/percent format; no guessing of histogram semantics."""
    if not isinstance(dvh_data, dict) or 'dose_bins_Gy' not in dvh_data or 'volume_percent' not in dvh_data:
        raise RadiobiologyBoundsError("DVH requires dose_bins_Gy and volume_percent arrays.")
    doses=np.asarray(dvh_data['dose_bins_Gy'],dtype=float)
    volumes=np.asarray(dvh_data['volume_percent'],dtype=float)
    if doses.ndim!=1 or volumes.ndim!=1 or len(doses)!=len(volumes) or len(doses)<2:
        raise RadiobiologyBoundsError("Matching one-dimensional DVH arrays of length >=2 are required.")
    PhysicsValidationEngine.validate_dose_grid(doses,raise_on_fail=True)
    if not np.isfinite(volumes).all() or (volumes<0).any() or (volumes>100).any() or volumes.sum()<=0 or (np.diff(doses)<=0).any():
        raise RadiobiologyBoundsError("Ordered doses and finite nonnegative volume percentages are required.")
    if dvh_type=='cumulative':
        if doses[0]!=0 or not np.isclose(volumes[0],100,atol=1e-6) or volumes[-1]!=0 or (np.diff(volumes)>0).any():
            raise RadiobiologyBoundsError("Cumulative DVH must start at 0 Gy/100%, decrease monotonically and end at zero volume.")
        weights=-np.diff(volumes)
        return .5*(doses[:-1]+doses[1:]),weights/weights.sum()
    if dvh_type=='differential':
        if not np.isclose(volumes.sum(),100,atol=1e-6):
            raise RadiobiologyBoundsError("Differential volume percentages must sum to 100.")
        return doses,volumes/volumes.sum()
    raise RadiobiologyBoundsError("dvh_type must be cumulative or differential.")


def _eud(doses,fracs,power):
    mask=fracs>0
    d,v=doses[mask],fracs[mask]
    if power<0 and (d==0).any():
        return 0.
    positive=d>0
    if not positive.any():return 0.
    return float(np.exp(logsumexp(np.log(v[positive])+power*np.log(d[positive]))/power))


@audited_operation
def calculate_tcp_ntcp(
    dvh_data: Dict[str, List[float]],
    model_type: str,
    parameters: Dict[str, float],
    dvh_type: str = "cumulative",
) -> Dict[str, float]:
    """Calculates Tumor Control Probability (TCP) or Normal Tissue Complication Probability (NTCP)

    using radiobiological parameters and equivalent uniform dose (EUD).
    """
    mid_doses, fracs = _extract_diff_dvh(dvh_data, dvh_type)
    m_type = model_type.strip().upper()

    # Parameter lookup helper (case insensitive)
    params_norm = {k.lower().replace("_", ""): float(v) for k, v in parameters.items()}

    if not all(np.isfinite(v) for v in params_norm.values()):
        raise RadiobiologyBoundsError("Model parameters must be finite.")

    if m_type in ("LKB", "LYMAN"):
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
        eud = _eud(mid_doses,fracs,inv_n)

        # Normalized variable t = (EUD - TD50) / (m * TD50)
        t = (eud - td50) / (m * td50)

        # Standard normal cumulative distribution function
        ntcp = float(0.5 * (1.0 + erf(t / math.sqrt(2.0))))
        ntcp = max(0.0, min(1.0, ntcp))

        res = {
            "model": "Lyman-Kutcher-Burman (LKB)",
            "EUD_Gy": eud,
            "NTCP": ntcp,
            "t_score": round(t, 3),
            "TD50_Gy": td50,
            "m_slope": m,
            "n_volume_effect": n,
        }

        if not np.isfinite(eud):
            raise RadiobiologyBoundsError("EUD is nonfinite; review numerical conditioning.")
        res.update(clinical_release=False, dvh_type=dvh_type, parameters_used=parameters,
                   limitations=["No fractionation conversion, parameter uncertainty or clinical calibration."])
        PhysicsValidationEngine.validate_radiobiology(res, raise_on_fail=True)
        return res

    elif m_type in ("POISSON_LQ", "POISSON_TCP"):
        # Poisson-LQ / Logistic TCP Model
        # Required: TCD50 (or TD50), gamma50 (or gamma_50)
        tcd50 = params_norm.get("tcd50")
        gamma50 = params_norm.get("gamma50")
        a_param = params_norm.get("a", -10.0)  # tumor volume effect exponent

        if tcd50 is None or tcd50 <= 0:
            raise RadiobiologyBoundsError("TCP parameter 'TCD50' must be > 0 Gy.")
        if gamma50 is None or gamma50 <= 0:
            raise RadiobiologyBoundsError("TCP slope parameter 'gamma_50' must be > 0.")

        if a_param >= 0:
            raise RadiobiologyBoundsError("Tumor EUD exponent a must be negative.")

        # Generalized EUD for tumor
        # Cold spots dominate tumor control -> negative exponent
        eud = _eud(mid_doses,fracs,a_param)

        # Poisson TCP form: TCP = (0.5) ** exp((2 * gamma50 / ln2) * (1 - EUD / TCD50))
        exponent = (2.0 * gamma50 / math.log(2.0)) * (1.0 - (eud / tcd50))
        # Prevent numerical overflow
        clamped_exp = max(-50.0, min(50.0, exponent))
        tcp = float((0.5) ** math.exp(clamped_exp))
        tcp = max(0.0, min(1.0, tcp))

        res = {
            "model": "Poisson EUD TCP (no fractionation correction)",
            "EUD_Gy": eud,
            "TCP": tcp,
            "TCD50_Gy": tcd50,
            "gamma50": gamma50,
        }

        if not np.isfinite(eud):
            raise RadiobiologyBoundsError("EUD is nonfinite; review numerical conditioning.")
        res.update(clinical_release=False, dvh_type=dvh_type, parameters_used=parameters,
                   limitations=["No fractionation conversion, parameter uncertainty or clinical calibration."])
        PhysicsValidationEngine.validate_radiobiology(res, raise_on_fail=True)
        return res

    else:
        raise ValueError(f"Unknown model_type '{model_type}'. Choose 'LKB' or 'Poisson_LQ'.")
