"""Label-free fixed-cardinality calibration, preserving fixed-size log-odds ranks."""

import numpy as np

from .errors import DomainError

CONTRACT = {"version": "red-logit-intercept-mass6-v1", "target_mass": 6,
            "iterations": 80, "uses_outcomes": False,
            "ranking": "every_six_subset_score_adds_the_same_6_times_intercept"}


def calibrate(values):
    p = np.asarray(values, dtype=np.float64)
    if p.shape != (33,) or not np.isfinite(p).all() or not ((p > 0) & (p < 1)).all():
        raise DomainError("RED_CALIBRATION_INPUT", "Expected33 finite interior marginal probabilities")
    logits = np.log(p) - np.log1p(-p)
    low, high = -80.0 - float(logits.max()), 80.0 - float(logits.min())
    for _ in range(CONTRACT["iterations"]):
        middle = (low + high) / 2
        mass = (1 / (1 + np.exp(-np.clip(logits + middle, -700, 700)))).sum()
        if mass > CONTRACT["target_mass"]:
            high = middle
        else:
            low = middle
    result = 1 / (1 + np.exp(-np.clip(logits + (low + high) / 2, -700, 700)))
    if not np.isfinite(result).all() or abs(float(result.sum()) - 6) > 1e-10:
        raise DomainError("RED_CALIBRATION_MASS", "The predicted number of red balls must equal6")
    return result
