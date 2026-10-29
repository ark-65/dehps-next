"""Bounded neural experiments. A fitter receives only the prior prefix, never target labels."""

import hashlib
import math
import time

import numpy as np
import torch
from torch import nn

from .domain import digest, timestamp
from .errors import DomainError
from .model import Recipe, RedBlueNet, encode_torch, load_torch, vectors, weight_digest


def validate_spec(spec):
    allowed = {"method", "window", "hidden", "epochs", "learning_rate", "weight_decay", "train_history"}
    if set(spec) != allowed or spec["method"] not in ("raw", "fft"):
        raise DomainError("INVALID_RESEARCH_SPEC", "Unknown feature, method or parameter")
    if any(type(spec[k]) is not int for k in ("window", "hidden", "epochs", "train_history")):
        raise DomainError("INVALID_RESEARCH_SPEC", "Integer model parameters required")
    Recipe(
        window=spec["window"],
        hidden=spec["hidden"],
        epochs=spec["epochs"],
        learning_rate=spec["learning_rate"],
    ).validate()
    if not 64 <= spec["train_history"] <= 1024 or not 0 <= spec["weight_decay"] <= 1:
        raise DomainError("RESEARCH_RESOURCE_LIMIT", "History or regularization exceeds research policy")
    return spec


def state_hash(value):
    h = hashlib.sha256()

    def visit(v):
        if isinstance(v, torch.Tensor):
            h.update(str((v.dtype, tuple(v.shape))).encode())
            h.update(v.detach().cpu().contiguous().numpy().tobytes())
        elif isinstance(v, dict):
            for k in sorted(v, key=str):
                h.update(str(k).encode())
                visit(v[k])
        elif isinstance(v, (list, tuple)):
            for item in v:
                visit(item)
        else:
            h.update(repr(v).encode())

    visit(value)
    return h.hexdigest()


def _features(windows, method):
    if method == "fft":
        spectrum = np.fft.rfft(windows, axis=1)
        spectrum[:, 4:, :] = 0
        windows = np.fft.irfft(spectrum, n=windows.shape[1], axis=1)
    return np.asarray(windows.reshape(len(windows), -1), dtype=np.float32)


def fit_prior(prior, spec, seed, pulse, initial=None):
    validate_spec(spec)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    window = spec["window"]
    start = max(window, len(prior) - spec["train_history"])
    if start >= len(prior):
        raise DomainError("INSUFFICIENT_RESEARCH_HISTORY", "No prior-only training windows")
    windows = np.stack([prior[i - window : i] for i in range(start, len(prior))])
    x = torch.from_numpy(_features(windows, spec["method"]))
    target = torch.from_numpy(prior[start:])
    blue_target = target[:, 33:].argmax(dim=1)
    prediction_input = torch.from_numpy(_features(prior[-window:][None, :, :], spec["method"]))
    recipe = Recipe(
        window=window, hidden=spec["hidden"], epochs=spec["epochs"], learning_rate=spec["learning_rate"]
    )
    model = RedBlueNet(recipe)
    optimizer = torch.optim.Adam(
        model.parameters(), lr=spec["learning_rate"], weight_decay=spec["weight_decay"]
    )
    inherited = False
    if initial:
        parent = load_torch(initial)
        if parent["spec"]["window"] == window and parent["spec"]["hidden"] == spec["hidden"]:
            model.load_state_dict(parent["model"])
            optimizer.load_state_dict(parent["optimizer"])
            for group in optimizer.param_groups:
                group["lr"], group["weight_decay"] = spec["learning_rate"], spec["weight_decay"]
            torch.set_rng_state(parent["rng"])
            inherited = True
    before = weight_digest(model)
    losses = []
    for _ in range(spec["epochs"]):
        pulse()
        optimizer.zero_grad()
        red_logits, blue_logits = model(x)
        loss = nn.functional.binary_cross_entropy_with_logits(red_logits, target[:, :33])
        loss = loss + nn.functional.cross_entropy(blue_logits, blue_target)
        if not torch.isfinite(loss):
            raise DomainError("RESEARCH_NONFINITE", "Non-finite candidate loss")
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 5)
        optimizer.step()
        losses.append(float(loss.detach()))
    with torch.no_grad():
        red_logits, blue_logits = model(prediction_input)
        red = torch.sigmoid(red_logits)[0].clamp(1e-7, 1 - 1e-7).numpy()
        blue = torch.softmax(blue_logits, dim=1)[0].numpy()
    if not np.isfinite(red).all() or not np.isfinite(blue).all():
        raise DomainError("RESEARCH_NONFINITE", "Invalid candidate probabilities")
    payload = {
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "rng": torch.get_rng_state(),
        "spec": spec,
        "weight_digest": weight_digest(model),
        "optimizer_digest": state_hash(optimizer.state_dict()),
        "initial_weight_digest": before,
        "inherited": inherited,
        "seed": seed,
        "gradient_steps": spec["epochs"],
        "loss": losses[-1],
    }
    return red, blue, payload


def compute_node(snapshot, spec, protocol, pulse, checkpoint, saved=None, initial=None, seconds=600):
    matrix = vectors(snapshot["rows"])
    all_origins = sorted(set(protocol["origins"] + protocol["reserve"]))
    identity = digest([spec, protocol["digest"], snapshot["cutoff"]])
    rows = []
    if saved:
        if saved["identity"] != identity:
            raise DomainError("RESEARCH_CHECKPOINT_CHANGED", "Research checkpoint input differs")
        rows = saved["rows"]
        if [r["origin"] for r in rows] != all_origins[: len(rows)]:
            raise DomainError("RESEARCH_CHECKPOINT_GAP", "Research cursor is not a prefix")
    start = time.monotonic()
    for position in range(len(rows), len(all_origins)):
        pulse()
        if time.monotonic() - start > seconds:
            raise DomainError("RESEARCH_TIME_BUDGET", "Per-attempt compute budget exhausted")
        origin = all_origins[position]
        history = snapshot["rows"][:origin]
        if timestamp(history[-1]["available_at"]) >= timestamp(snapshot["rows"][origin]["draw_at"]):
            raise DomainError(
                "RESEARCH_FUTURE_LEAK", "A label is not prior-available at its evaluation origin"
            )
        red, blue, trained = fit_prior(matrix[:origin], spec, protocol["seed"] + origin, pulse)
        actual = snapshot["rows"][origin]
        red_target = np.zeros(33)
        red_target[np.array(actual["red"]) - 1] = 1
        rows.append(
            {
                "origin": origin,
                "issue": actual["issue"],
                "training_through": history[-1]["issue"],
                "blue_log_loss": -math.log(max(float(blue[actual["blue"] - 1]), 1e-12)),
                "blue_hit": int(int(blue.argmax()) + 1 == actual["blue"]),
                "red_brier": float(np.mean((red - red_target) ** 2)),
                "blue_probabilities": blue.tolist(),
                "red_probabilities": red.tolist(),
                "weight_digest": trained["weight_digest"],
                "parameter_updated": trained["weight_digest"] != trained["initial_weight_digest"],
            }
        )
        if len(rows) % 8 == 0 or len(rows) == len(all_origins):
            checkpoint({"identity": identity, "rows": rows})
    # A current anchor is never reused for historical-origin validation.
    _, _, anchor = fit_prior(matrix, spec, protocol["seed"], pulse, initial=initial)
    anchor["through_issue"] = snapshot["rows"][-1]["issue"]
    return (
        rows,
        encode_torch(anchor),
        {
            "seconds_this_attempt": round(time.monotonic() - start, 4),
            "resumed_origins": len(saved["rows"]) if saved else 0,
            "actual_gradient_steps": len(all_origins) * spec["epochs"] + spec["epochs"],
            "anchor_weight_digest": anchor["weight_digest"],
            "anchor_optimizer_digest": anchor["optimizer_digest"],
            "all_origin_parameters_updated": all(r["parameter_updated"] for r in rows),
        },
    )


def restore_anchor(data):
    anchor = load_torch(data)
    spec = anchor["spec"]
    model = RedBlueNet(Recipe(window=spec["window"], hidden=spec["hidden"]))
    model.load_state_dict(anchor["model"])
    optimizer = torch.optim.Adam(model.parameters())
    optimizer.load_state_dict(anchor["optimizer"])
    torch.set_rng_state(anchor["rng"])
    if (
        weight_digest(model) != anchor["weight_digest"]
        or state_hash(optimizer.state_dict()) != anchor["optimizer_digest"]
    ):
        raise DomainError("ROLLBACK_ANCHOR_CORRUPT", "Parent model or optimizer digest differs")
    return {
        "weight_digest": weight_digest(model),
        "optimizer_digest": state_hash(optimizer.state_dict()),
        "rng_restored": True,
        "through_issue": anchor["through_issue"],
    }
