"""Prior-only shared-parameter probability models; feature contract multiscale-v1."""

import math
from itertools import product

import numpy as np
import torch
from torch import nn

from .errors import DomainError
from .model import weight_digest

VERSION = "multiscale-v1"
METHODS = ("dynamic_level_v1", "dynamic_trend_v1", "dynamic_full_v1", "dynamic_no_short_v1")
FEATURES = {
    METHODS[0]: (0, 1, 2),
    METHODS[1]: (0, 1, 2, 3, 4),
    METHODS[2]: (0, 1, 2, 3, 4, 5),
    METHODS[3]: (1, 2, 4, 5),
}
TOPIC = {
    "name": "multiscale-probability-v1",
    "methods": list(METHODS),
    "question": "Do causal10/30/100 frequencies, trends and gaps improve calibrated next-issue probabilities and unchanged paired hit gates?",
}


def initial_specs():
    return [
        {"method": m, "window": 100, "hidden": 8, "epochs": 100, "learning_rate": 0.01,
         "weight_decay": decay, "train_history": history}
        for m, history, decay in product(METHODS, (256, 512, 1024), (0.01, 0.1, 1.0))
    ]


def validate(spec):
    if (spec["method"] not in METHODS or spec["window"] != 100 or spec["hidden"] != 8
            or not 1 <= spec["epochs"] <= 200 or not 64 <= spec["train_history"] <= 1024
            or not 0 < spec["learning_rate"] <= 0.1 or not 0 <= spec["weight_decay"] <= 1):
        raise DomainError("MULTISCALE_SPEC", "Versioned shared-logit model requires100 history and hidden8 sentinel")
    return spec


def features(matrix, indices, method):
    """Each row t depends exclusively on [t-100,t); no target or future access."""
    matrix = np.asarray(matrix, dtype=np.float64)
    indices = np.asarray(indices, dtype=int)
    if matrix.ndim != 2 or matrix.shape[1] != 49 or not len(indices) or indices.min() < 100 or indices.max() > len(matrix):
        raise DomainError("MULTISCALE_HISTORY", "Require100 complete prior draws for each feature row")
    prefix = np.vstack([np.zeros((1, 49)), np.cumsum(matrix, axis=0)])
    base = np.r_[np.full(33, 6 / 33), np.full(16, 1 / 16)]
    rates = [(prefix[indices] - prefix[indices - w] + 20 * base) / (w + 20) for w in (10, 30, 100)]
    gaps = np.ones((len(indices), 49), dtype=np.float64)
    for k, t in enumerate(indices):
        reverse = matrix[t-100:t][::-1] > 0
        gaps[k] = np.where(reverse.any(axis=0), reverse.argmax(axis=0), 100) / 100
    value = np.stack([*rates, rates[0] - rates[1], rates[1] - rates[2], gaps], axis=-1)
    return value[..., list(FEATURES[method])]


class SharedLogits(nn.Module):
    def __init__(self, dimensions):
        super().__init__()
        self.red = nn.Linear(dimensions, 1)
        self.blue = nn.Linear(dimensions, 1)
        # Same feature/number symmetry; no fixed identifier preference.
        nn.init.zeros_(self.red.weight)
        nn.init.constant_(self.red.bias, math.log(6 / 27))
        nn.init.zeros_(self.blue.weight)
        nn.init.zeros_(self.blue.bias)

    def forward(self, x):
        return self.red(x[:, :33]).squeeze(-1), self.blue(x[:, 33:]).squeeze(-1)


def probabilities(red_logits, blue_logits):
    r = np.asarray(red_logits, dtype=np.float64)
    low, high = -80.0 - float(r.max()), 80.0 - float(r.min())
    for _ in range(80):
        middle = (low + high) / 2
        if (1 / (1 + np.exp(-np.clip(r + middle, -700, 700)))).sum() > 6:
            high = middle
        else:
            low = middle
    red = 1 / (1 + np.exp(-np.clip(r + (low + high) / 2, -700, 700)))
    blue = np.exp(np.asarray(blue_logits, dtype=np.float64) - np.max(blue_logits))
    blue = np.maximum(blue / blue.sum(), 1e-12)
    blue /= blue.sum()
    if not np.isfinite(red).all() or not np.isfinite(blue).all() or abs(red.sum() - 6) > 1e-6:
        raise DomainError("MULTISCALE_PROBABILITY", "Probability conservation failed")
    return red, blue


def fit(prior, spec, seed, pulse, initial=None):
    from .research_compute import state_hash

    validate(spec)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    start = max(100, len(prior) - spec["train_history"])
    if start >= len(prior):
        raise DomainError("MULTISCALE_HISTORY", "Need historical targets after feature warmup")
    indices = np.arange(start, len(prior))
    raw = features(prior, indices, spec["method"])
    # Separate colour scales, fitted only on training feature rows.
    mean = np.stack([raw[:, :33].mean((0, 1)), raw[:, 33:].mean((0, 1))])
    scale = np.stack([raw[:, :33].std((0, 1)), raw[:, 33:].std((0, 1))])
    scale = np.maximum(scale, 1e-6)
    pre = np.concatenate([(raw[:, :33] - mean[0]) / scale[0], (raw[:, 33:] - mean[1]) / scale[1]], axis=1)
    x = torch.tensor(pre, dtype=torch.float32)
    y = torch.tensor(prior[indices], dtype=torch.float32)
    model = SharedLogits(raw.shape[-1])
    optimizer = torch.optim.Adam(model.parameters(), lr=spec["learning_rate"], weight_decay=spec["weight_decay"])
    # Fresh fit: changing the prefix changes standardization; do not inherit incompatible coefficients.
    before = weight_digest(model)
    for _ in range(spec["epochs"]):
        pulse()
        optimizer.zero_grad()
        red_logits, blue_logits = model(x)
        loss = nn.functional.binary_cross_entropy_with_logits(red_logits, y[:, :33])
        loss = loss + nn.functional.cross_entropy(blue_logits, y[:, 33:].argmax(1))
        if not torch.isfinite(loss):
            raise DomainError("MULTISCALE_NONFINITE", "Nonfinite shared-logit fit")
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 5)
        optimizer.step()
    mathematical = {
        "feature_version": VERSION, "features": list(FEATURES[spec["method"]]),
        "mean": torch.tensor(mean), "scale": torch.tensor(scale), "smoothing": 20,
        "red_projection": "common-logit-offset-sum6-v1", "fit_rows": len(indices),
        "training_start": int(start), "training_end_exclusive": len(prior),
    }
    payload = {
        "model_type": VERSION, "model": model.state_dict(), "optimizer": optimizer.state_dict(),
        "rng": torch.get_rng_state(), "spec": spec, "seed": seed,
        "weight_digest": weight_digest(model), "initial_weight_digest": before,
        "optimizer_digest": state_hash(optimizer.state_dict()), "inherited": False,
        "gradient_steps": spec["epochs"], "loss": float(loss.detach()),
        "mathematical": mathematical, "mathematical_digest": state_hash(mathematical),
    }
    red, blue = predict(payload, prior)
    return red, blue, payload


def restore(anchor):
    from .research_compute import state_hash

    validate(anchor["spec"])
    math_state = anchor["mathematical"]
    if (anchor.get("model_type") != VERSION or math_state.get("feature_version") != VERSION
            or math_state.get("features") != list(FEATURES[anchor["spec"]["method"]])):
        raise DomainError("MULTISCALE_ANCHOR_CONTRACT", "Incompatible model/feature version")
    model = SharedLogits(len(math_state["features"]))
    model.load_state_dict(anchor["model"])
    optimizer = torch.optim.Adam(model.parameters())
    optimizer.load_state_dict(anchor["optimizer"])
    if (weight_digest(model) != anchor["weight_digest"]
            or state_hash(optimizer.state_dict()) != anchor["optimizer_digest"]
            or state_hash(math_state) != anchor["mathematical_digest"]):
        raise DomainError("MULTISCALE_ANCHOR_CORRUPT", "Model, optimizer or preprocessing changed")
    torch.set_rng_state(anchor["rng"])
    return model


def predict(anchor, matrix):
    model = restore(anchor)
    math_state = anchor["mathematical"]
    raw = features(matrix, [len(matrix)], anchor["spec"]["method"])
    mean, scale = math_state["mean"].numpy(), math_state["scale"].numpy()
    raw[:, :33] = (raw[:, :33] - mean[0]) / scale[0]
    raw[:, 33:] = (raw[:, 33:] - mean[1]) / scale[1]
    with torch.no_grad():
        red, blue = model(torch.tensor(raw, dtype=torch.float32))
    return probabilities(red[0].numpy(), blue[0].numpy())


def is_dynamic(spec):
    return spec.get("method") in METHODS
