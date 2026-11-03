"""Descriptive, per-issue paired probability audits; never promotion gates."""

import math

import numpy as np

from .model import vectors
from .research_protocol import _interval


def _curve(probabilities, targets):
    p, y = np.asarray(probabilities).ravel(), np.asarray(targets).ravel()
    result = []
    for lo, hi in zip(np.linspace(0, 1, 11)[:-1], np.linspace(0, 1, 11)[1:]):
        mask = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        result.append({"lower": float(lo), "upper": float(hi), "number_events": int(mask.sum()),
                       "predicted": float(p[mask].mean()) if mask.any() else None,
                       "observed": float(y[mask].mean()) if mask.any() else None})
    return result


def diagnose(rows, snapshot, protocol, parent_rows=None):
    from .research_hits import _red_hits

    matrix = vectors(snapshot["rows"])
    lookup = {r["origin"]: r for r in rows}
    parent = {r["origin"]: r for r in parent_rows} if parent_rows else None
    windows = {}
    uniform = np.r_[np.full(33, 6 / 33), np.full(16, 1 / 16)]
    for key in ("recent", "recent50", "recent10"):
        if key not in protocol:
            continue
        per_issue, reds, blues, ys, states = [], [], [], [], []
        for i in protocol[key]:
            r, actual = lookup[i], matrix[i]
            red, blue = np.array(r["red_probabilities"]), np.array(r["blue_probabilities"])
            smoothed = (matrix[max(0, i-100):i].sum(0) + 20 * uniform) / (min(100, i) + 20)
            metrics = {"model_red_brier": float(np.mean((red-actual[:33])**2)),
                       "model_blue_log_loss": -math.log(max(float(blue[actual[33:].argmax()]), 1e-12))}
            red_target = snapshot["rows"][i]["red"]
            metrics["model_blue_hit"] = int(blue.argmax() == actual[33:].argmax())
            metrics["model_red5_hit"] = int(_red_hits(tuple(red), tuple(red_target))[0] >= 5)
            for name, values in (("uniform", uniform), ("smoothed100", smoothed)):
                metrics[name+"_red_brier"] = float(np.mean((values[:33]-actual[:33])**2))
                metrics[name+"_blue_log_loss"] = -math.log(max(float(values[33:][actual[33:].argmax()]), 1e-12))
                metrics[name+"_blue_hit"] = int(values[33:].argmax() == actual[33:].argmax())
                metrics[name+"_red5_hit"] = int(_red_hits(tuple(values[:33]), tuple(red_target))[0] >= 5)
            if parent:
                metrics["parent_red_brier"] = parent[i]["red_brier"]
                metrics["parent_blue_log_loss"] = parent[i]["blue_log_loss"]
                metrics["parent_blue_hit"] = parent[i]["blue_hit"]
                metrics["parent_red5_hit"] = int(_red_hits(tuple(parent[i]["red_probabilities"]), tuple(red_target))[0] >= 5)
            per_issue.append(metrics)
            reds.append(red)
            blues.append(blue)
            ys.append(actual)
            short = matrix[i-10:i].mean(0)
            long = matrix[max(0, i-100):i].mean(0)
            states.append(np.sign(short-long))
        target, state = np.array(ys), np.array(states)
        predicted = np.column_stack([np.array(reds), np.array(blues)])
        grouped = {}
        for label, selector in (("rising", state > 0), ("falling", state < 0), ("equal", state == 0)):
            grouped[label] = {}
            for colour, part in (("red", slice(0, 33)), ("blue", slice(33, 49))):
                mask, p, y = selector[:, part], predicted[:, part], target[:, part]
                grouped[label][colour] = {"number_events": int(mask.sum()),
                    "predicted": float(p[mask].mean()) if mask.any() else None,
                    "observed": float(y[mask].mean()) if mask.any() else None}
        paired = {}
        for name in ("uniform", "smoothed100", "parent") if parent else ("uniform", "smoothed100"):
            paired[name] = {}
            for metric in ("red_brier", "blue_log_loss", "red5_hit", "blue_hit"):
                delta = [m["model_"+metric]-m[name+"_"+metric] for m in per_issue]
                paired[name][metric] = {"mean_model_minus_baseline": float(np.mean(delta)),
                                       "paired_issue_interval95": _interval(delta, protocol)}
        windows[key] = {"n_unique_issues": len(per_issue),
            "means": {k: float(np.mean([r[k] for r in per_issue])) for k in per_issue[0]},
            "calibration": {"red": _curve(reds, target[:, :33]), "blue": _curve(blues, target[:, 33:])},
            "frequency_states": grouped, "paired": paired}
    return {"version": "probability-audit-v1", "windows": windows,
            "scope": "DESCRIPTIVE_DEVELOPMENT;CALIBRATION_AND_LOSS_NOT_HIT_PROMOTION;NO_FORWARD_PROOF",
            "resampling_unit": "ISSUE;NOT33_OR16_INDEPENDENT_DRAWS", "nested_windows_not_independent": True}


def svg(audit):
    """Small native vector calibration figure, derived only from recorded scores."""
    panels = []
    for k, colour in enumerate(("red", "blue")):
        offset = 320*k
        xy = [(offset+40+240*r["predicted"], 270-240*r["observed"])
                  for r in audit["windows"]["recent"]["calibration"][colour] if r["predicted"] is not None]
        points = " ".join(f"{x:.2f},{y:.2f}" for x,y in xy)
        marks = "".join(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{colour}"/>' for x,y in xy)
        panels.append(f'<text x="{offset+40}" y="20">{colour}: descriptive calibration</text>'
                      f'<path d="M{offset+40},30V270H{offset+280}" fill="none" stroke="black"/>'
                      f'<path d="M{offset+40},270L{offset+280},30" stroke="gray" stroke-dasharray="4"/>'
                      f'<polyline points="{points}" fill="none" stroke="{colour}" stroke-width="2"/>'+marks)
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="300" viewBox="0 0 640 300">'
            '<rect width="640" height="300" fill="white"/>'+"".join(panels)+'</svg>').encode()
