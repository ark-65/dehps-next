"""Bounded neural experiments. A fitter receives only the prior prefix, never target labels."""

import atexit
import hashlib
import math
import multiprocessing
import os
import signal
import threading
import time
from collections import deque

import numpy as np
import torch
from torch import nn

from .domain import digest, timestamp
from .errors import DomainError
from .model import Recipe, RedBlueNet, encode_torch, load_torch, vectors, weight_digest


def validate_spec(spec):
    allowed = {"method", "window", "hidden", "epochs", "learning_rate", "weight_decay", "train_history"}
    if set(spec) != allowed or spec["method"] not in ("raw", "fft", "ridge", "newton"):
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
        if (
            parent["spec"]["window"] == window
            and parent["spec"]["hidden"] == spec["hidden"]
            and parent["spec"]["method"] == spec["method"]
        ):
            model.load_state_dict(parent["model"])
            optimizer.load_state_dict(parent["optimizer"])
            for group in optimizer.param_groups:
                group["lr"], group["weight_decay"] = spec["learning_rate"], spec["weight_decay"]
            torch.set_rng_state(parent["rng"])
            inherited = True
    before = weight_digest(model)
    # Calibration uses a prior-only tail that is excluded from neural fitting.
    calibration = min(32, len(x) // 4) if spec["method"] == "newton" else 0
    fit_x = x[:-calibration] if calibration else x
    fit_target = target[:-calibration] if calibration else target
    fit_blue = blue_target[:-calibration] if calibration else blue_target
    losses = []
    for _ in range(spec["epochs"]):
        pulse()
        optimizer.zero_grad()
        red_logits, blue_logits = model(fit_x)
        loss = nn.functional.binary_cross_entropy_with_logits(red_logits, fit_target[:, :33])
        loss = loss + nn.functional.cross_entropy(blue_logits, fit_blue)
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
        mathematical = {"method": spec["method"]}
        if spec["method"] == "ridge":
            # A small residual head on causal window means, solved in primal form.
            z = np.column_stack([windows.mean(axis=1), np.ones(len(windows))]).astype(np.float64)
            red_fit, blue_fit = model(x)
            fitted = np.column_stack([torch.sigmoid(red_fit).numpy(), torch.softmax(blue_fit, 1).numpy()])
            residual = target.numpy() - fitted
            penalty = np.eye(z.shape[1]) * 10.0
            penalty[-1, -1] = 0.01
            coefficients = np.linalg.solve(z.T @ z + penalty, z.T @ residual)
            query = np.append(prior[-window:].mean(axis=0), 1)
            adjustment = query @ coefficients
            red = np.clip(red + 0.25 * adjustment[:33], 1e-7, 1 - 1e-7)
            blue = np.clip(blue + 0.25 * adjustment[33:], 1e-7, None)
            blue /= blue.sum()
            mathematical.update(
                coefficients=torch.from_numpy(coefficients), ridge_penalty=10.0, blend=0.25, fit_rows=len(z)
            )
        elif spec["method"] == "newton":
            from .research_math import temperature_newton

            _, calibration_logits = model(x[-calibration:])
            result = temperature_newton(calibration_logits.numpy(), blue_target[-calibration:].numpy())
            blue = torch.softmax(blue_logits / result["temperature"], dim=1)[0].numpy()
            mathematical.update(result, calibration_rows=calibration)
        elif spec["method"] == "fft":
            mathematical.update(retained_frequency_bins=4, axis="prior_window_only")
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
        "mathematical": mathematical,
        "mathematical_digest": state_hash(mathematical),
    }
    return red, blue, payload


_ORIGIN_CANCEL = None
_ORIGIN_POOL = None
_ORIGIN_POOL_KEY = None
_ORIGIN_PARENT_CANCEL = None


def _origin_initializer(threads, cancel):
    global _ORIGIN_CANCEL
    _ORIGIN_CANCEL = cancel
    # Spawn gives every fitter its own RNG and parameter/optimizer state.
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    torch.set_num_threads(threads)
    torch.set_num_interop_threads(1)


def _fit_origin(prior, spec, seed):
    def pulse():
        if _ORIGIN_CANCEL.is_set():
            raise DomainError("ORIGIN_CANCELLED", "Parent ended the origin batch")

    try:
        red, blue, trained = fit_prior(prior, spec, seed, pulse)
    except DomainError as exc:
        # DomainError has a custom constructor; transmit data instead of unpickling exceptions.
        return {"error": exc.code, "message": str(exc)}
    return (
        red,
        blue,
        {key: trained[key] for key in ("weight_digest", "initial_weight_digest", "mathematical_digest")},
    )


def close_origin_pool():
    global _ORIGIN_POOL, _ORIGIN_POOL_KEY, _ORIGIN_PARENT_CANCEL
    if _ORIGIN_POOL is None:
        return
    pool, cancel = _ORIGIN_POOL, _ORIGIN_PARENT_CANCEL
    _ORIGIN_POOL = _ORIGIN_POOL_KEY = _ORIGIN_PARENT_CANCEL = None
    cancel.set()
    watchdog = threading.Timer(5, lambda: os._exit(70))
    watchdog.daemon = True
    watchdog.start()
    try:
        pool.close()
        pool.join()
    finally:
        watchdog.cancel()


atexit.register(close_origin_pool)


def _origin_pool(processes, threads):
    global _ORIGIN_POOL, _ORIGIN_POOL_KEY, _ORIGIN_PARENT_CANCEL
    if _ORIGIN_POOL_KEY != (processes, threads):
        close_origin_pool()
        context = multiprocessing.get_context("spawn")
        _ORIGIN_PARENT_CANCEL = context.Event()
        _ORIGIN_POOL = context.Pool(
            processes, initializer=_origin_initializer, initargs=(threads, _ORIGIN_PARENT_CANCEL)
        )
        _ORIGIN_POOL_KEY = (processes, threads)
    return _ORIGIN_POOL


def _origin_results(matrix, spec, protocol, origins, pulse, processes, threads):
    if processes == 1:
        for origin in origins:
            pulse()
            yield origin, fit_prior(matrix[:origin], spec, protocol["seed"] + origin, pulse)
        return
    if not origins:
        return
    # Only prior prefixes cross the process boundary. Labels stay in the parent scorer.
    pool = _origin_pool(processes, threads)
    pending = deque()
    cursor = iter(origins)

    def submit():
        origin = next(cursor, None)
        if origin is not None:
            pulse()
            pending.append(
                (origin, pool.apply_async(_fit_origin, (matrix[:origin], spec, protocol["seed"] + origin)))
            )

    complete = False
    try:
        for _ in range(processes):
            submit()
        while pending:
            origin, future = pending.popleft()
            while not future.ready():
                pulse()
                future.wait(0.02)
            pulse()
            value = future.get()
            if isinstance(value, dict) and "error" in value:
                raise DomainError(value["error"], value["message"])
            yield origin, value
            submit()
        complete = True
    finally:
        if not complete:
            close_origin_pool()
        # Completed pools stay idle for later nodes; pause/lease loss always closes them.


def compute_node(
    snapshot,
    spec,
    protocol,
    pulse,
    checkpoint,
    saved=None,
    initial=None,
    seconds=600,
    include_reserve=True,
    processes=1,
    threads=None,
):
    matrix = vectors(snapshot["rows"])
    all_origins = sorted(protocol["origins"]) + (sorted(protocol["reserve"]) if include_reserve else [])
    identity = digest([spec, protocol["digest"], snapshot["cutoff"]])
    rows = []
    if saved:
        if saved["identity"] != identity:
            raise DomainError("RESEARCH_CHECKPOINT_CHANGED", "Research checkpoint input differs")
        rows = list(saved["rows"])
        if [r["origin"] for r in rows] != all_origins[: len(rows)]:
            raise DomainError("RESEARCH_CHECKPOINT_GAP", "Research cursor is not a prefix")
    restored_origins = len(rows)
    start = time.monotonic()
    if not 1 <= processes <= 8:
        raise DomainError("RESEARCH_PARALLELISM_LIMIT", "Expected one to eight isolated origin fitters")
    threads = threads or torch.get_num_threads()
    if threads != torch.get_num_threads():
        raise DomainError("NUMERIC_THREADS_CHANGED", "Parent/child fitter threads must match frozen contract")
    if processes > 1 and threads not in (1, 2, 4, 8):
        raise DomainError(
            "PARALLEL_THREADS_UNAUDITED", "Parallel origin execution requires an audited thread count"
        )
    remaining = all_origins[len(rows) :]
    # Verify the legal boundary before submitting any prefix to a child.
    for origin in remaining:
        if timestamp(snapshot["rows"][origin - 1]["available_at"]) >= timestamp(
            snapshot["rows"][origin]["draw_at"]
        ):
            raise DomainError(
                "RESEARCH_FUTURE_LEAK", "A label is not prior-available at its evaluation origin"
            )

    def bounded_pulse():
        pulse()
        if time.monotonic() - start > seconds:
            raise DomainError("YIELD_COMPUTE_SLICE", "Save completed origins and renew the execution slice")

    results = _origin_results(matrix, spec, protocol, remaining, bounded_pulse, processes, threads)
    try:
        for origin, (red, blue, trained) in results:
            history = snapshot["rows"][:origin]
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
                    "mathematical_digest": trained["mathematical_digest"],
                }
            )
            if len(rows) % 8 == 0 or len(rows) == len(all_origins):
                checkpoint({"identity": identity, "rows": rows})
    except DomainError as exc:
        if exc.code.startswith("YIELD_") or exc.code == "INTERRUPTED":
            # Flush the completed prefix without asking the pause gate to permit more training.
            checkpoint({"identity": identity, "rows": rows})
        raise
    finally:
        results.close()
    bounded_pulse()
    # A current anchor is never reused for historical-origin validation.
    _, _, anchor = fit_prior(matrix, spec, protocol["seed"], bounded_pulse, initial=initial)
    anchor["through_issue"] = snapshot["rows"][-1]["issue"]
    publication = anchor
    if anchor["inherited"]:
        # Historical scores start fresh at every origin. Publish that same training procedure,
        # while retaining the inherited optimizer/RNG anchor for the research branch itself.
        _, _, publication = fit_prior(matrix, spec, protocol["seed"], bounded_pulse)
        publication["through_issue"] = anchor["through_issue"]
    return (
        rows,
        encode_torch(anchor),
        encode_torch(publication),
        {
            "seconds_this_attempt": round(time.monotonic() - start, 4),
            "origin_processes": processes,
            "threads_per_origin": threads,
            "origin_cpu_limit": min(20, processes * threads),
            "resumed_origins": restored_origins,
            "origin_fits_executed_this_attempt": len(all_origins) - restored_origins,
            "gradient_steps_executed_this_attempt": (
                len(all_origins) - restored_origins + 1 + int(anchor["inherited"])
            )
            * spec["epochs"],
            "committed_origin_and_anchor_steps": (len(all_origins) + 1 + int(anchor["inherited"]))
            * spec["epochs"],
            "publication_anchor_fresh": not publication["inherited"],
            "publication_weight_digest": publication["weight_digest"],
            "step_count_scope": "unique_completed_fits;excludes_interrupted_or_recomputed_work",
            "anchor_weight_digest": anchor["weight_digest"],
            "anchor_optimizer_digest": anchor["optimizer_digest"],
            "anchor_mathematical_digest": anchor["mathematical_digest"],
            "anchor_inherited_compatible_parent": anchor["inherited"],
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
    if "mathematical" in anchor and state_hash(anchor["mathematical"]) != anchor["mathematical_digest"]:
        raise DomainError("ROLLBACK_MATH_CORRUPT", "Parent mathematical state digest differs")
    return {
        "weight_digest": weight_digest(model),
        "optimizer_digest": state_hash(optimizer.state_dict()),
        "rng_restored": True,
        "rng_digest": state_hash(torch.get_rng_state()),
        "mathematical_digest": anchor.get("mathematical_digest"),
        "through_issue": anchor["through_issue"],
    }


def predict_anchor(data, rows):
    """Infer the exact selected anchor, retaining its FFT/ridge/Newton transformation."""
    restore_anchor(data)
    anchor = load_torch(data)
    spec = anchor["spec"]
    if anchor["through_issue"] != rows[-1]["issue"]:
        raise DomainError("ANCHOR_DATA_CHANGED", "Current anchor must cover exactly the validated dataset")
    model = RedBlueNet(Recipe(window=spec["window"], hidden=spec["hidden"]))
    model.load_state_dict(anchor["model"])
    model.eval()
    matrix = vectors(rows)
    with torch.no_grad():
        red_logits, blue_logits = model(
            torch.from_numpy(_features(matrix[-spec["window"] :][None], spec["method"]))
        )
        red = torch.sigmoid(red_logits)[0].clamp(1e-7, 1 - 1e-7).numpy()
        blue = torch.softmax(blue_logits, 1)[0].numpy()
        math_state = anchor["mathematical"]
        if spec["method"] == "ridge":
            query = np.append(matrix[-spec["window"] :].mean(0), 1)
            adjustment = query @ math_state["coefficients"].numpy()
            red = np.clip(red + math_state["blend"] * adjustment[:33], 1e-7, 1 - 1e-7)
            blue = np.clip(blue + math_state["blend"] * adjustment[33:], 1e-7, None)
            blue /= blue.sum()
        elif spec["method"] == "newton":
            blue = torch.softmax(blue_logits / math_state["temperature"], 1)[0].numpy()
    from .domain import top_red_combinations

    return {
        "red_probabilities": red.tolist(),
        "blue_probabilities": blue.tolist(),
        "blue_top1": int(blue.argmax()) + 1,
        "red_top100": top_red_combinations(red.tolist()),
        "ranking_score": "sum_of_marginal_log_odds_not_joint_probability",
    }
