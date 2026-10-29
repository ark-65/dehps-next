import hashlib
import io
import json
import random
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from .domain import top_red_combinations
from .errors import DomainError


@dataclass(frozen=True)
class Recipe:
    window: int = 16
    hidden: int = 128
    epochs: int = 20
    learning_rate: float = 0.002
    seed: int = 1729

    def validate(self):
        if not 2 <= self.window <= 64 or not 8 <= self.hidden <= 256 or not 1 <= self.epochs <= 200:
            raise DomainError("RECIPE_BUDGET", "Model recipe exceeds P1 limits")
        if not 0 < self.learning_rate <= 0.1 or not 0 <= self.seed < 2**31:
            raise DomainError("INVALID_RECIPE", "Invalid learning rate or seed")


class RedBlueNet(nn.Module):
    def __init__(self, recipe):
        super().__init__()
        self.encoder = nn.Sequential(nn.Linear(recipe.window * 49, recipe.hidden), nn.Tanh())
        self.red = nn.Linear(recipe.hidden, 33)
        self.blue = nn.Linear(recipe.hidden, 16)

    def forward(self, values):
        hidden = self.encoder(values)
        return self.red(hidden), self.blue(hidden)


def vectors(rows):
    values = np.zeros((len(rows), 49), dtype=np.float32)
    for i, row in enumerate(rows):
        values[i, np.array(row["red"]) - 1] = 1
        values[i, 33 + row["blue"] - 1] = 1
    return values


def weight_digest(model):
    h = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        h.update(name.encode())
        h.update(value.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def encode_torch(payload):
    buffer = io.BytesIO()
    torch.save(payload, buffer)
    return buffer.getvalue()


def load_torch(data):
    return torch.load(io.BytesIO(data), map_location="cpu", weights_only=True)


def train(snapshot_bytes, recipe, parent_bytes, checkpoint_bytes, save_checkpoint, pulse):
    recipe.validate()
    torch.manual_seed(recipe.seed)
    torch.use_deterministic_algorithms(True)
    snapshot = json.loads(snapshot_bytes)
    rows = snapshot["rows"]
    if not recipe.window + 2 <= len(rows) <= 5000:
        raise DomainError("INSUFFICIENT_HISTORY", "History must contain window+2..5000 rows")
    values = vectors(rows)
    x = torch.from_numpy(
        np.stack([values[i - recipe.window : i].ravel() for i in range(recipe.window, len(rows))])
    )
    red = torch.from_numpy(values[recipe.window :, :33])
    blue = torch.tensor([row["blue"] - 1 for row in rows[recipe.window :]], dtype=torch.long)
    model = RedBlueNet(recipe)
    optimizer = torch.optim.Adam(model.parameters(), lr=recipe.learning_rate)
    if parent_bytes:
        parent = load_torch(parent_bytes)
        model.load_state_dict(parent["model"])
        optimizer.load_state_dict(parent["optimizer"])
    initial_digest = weight_digest(model)
    first_epoch = 0
    if checkpoint_bytes:
        saved = load_torch(checkpoint_bytes)
        if saved["snapshot_sha256"] != hashlib.sha256(snapshot_bytes).hexdigest():
            raise DomainError("CHECKPOINT_INPUT_CHANGED", "Checkpoint is bound to another snapshot")
        model.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        first_epoch, initial_digest = saved["epoch"], saved["initial_digest"]
        torch.set_rng_state(saved["rng"])
    losses = []
    for epoch in range(first_epoch, recipe.epochs):
        pulse()
        model.train()
        optimizer.zero_grad()
        red_logits, blue_logits = model(x)
        loss = nn.functional.binary_cross_entropy_with_logits(red_logits, red)
        loss = loss + nn.functional.cross_entropy(blue_logits, blue)
        if not torch.isfinite(loss):
            raise DomainError("NONFINITE_LOSS", "Training loss is not finite")
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
        losses.append(float(loss.detach()))
        if (epoch + 1) % 5 == 0:
            save_checkpoint(
                encode_torch(
                    {
                        "model": model.state_dict(),
                        "optimizer": optimizer.state_dict(),
                        "epoch": epoch + 1,
                        "rng": torch.get_rng_state(),
                        "initial_digest": initial_digest,
                        "snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
                    }
                ),
                epoch + 1,
            )
    final_digest = weight_digest(model)
    if final_digest == initial_digest:
        raise DomainError("NO_PARAMETER_UPDATE", "Zero parameter change cannot count as learning")
    manifest = {
        "parameters": sum(p.numel() for p in model.parameters()),
        "initial_weight_digest": initial_digest,
        "weight_digest": final_digest,
        "gradient_steps": recipe.epochs,
        "resumed_epoch": first_epoch,
        "loss_first_this_attempt": losses[0] if losses else None,
        "loss_last_this_attempt": losses[-1] if losses else None,
        "label_issues": [r["issue"] for r in rows[recipe.window :]],
        "context_issues": [r["issue"] for r in rows],
        "through_issue": rows[-1]["issue"],
        "torch_version": str(torch.__version__),
        "numpy_version": np.__version__,
        "device": "cpu",
        "threads": torch.get_num_threads(),
        "evidence": snapshot["mode"],
        "recipe": recipe.__dict__,
    }
    return encode_torch({"model": model.state_dict(), "optimizer": optimizer.state_dict()}), manifest


def predict(model_bytes, snapshot_bytes, recipe):
    rows = json.loads(snapshot_bytes)["rows"]
    model = RedBlueNet(recipe)
    model.load_state_dict(load_torch(model_bytes)["model"])
    model.eval()
    with torch.no_grad():
        red_logits, blue_logits = model(torch.from_numpy(vectors(rows)[-recipe.window :].reshape(1, -1)))
        red = torch.sigmoid(red_logits)[0].clamp(1e-7, 1 - 1e-7).tolist()
        blue = torch.softmax(blue_logits, dim=-1)[0].tolist()
    result = {
        "red_probabilities": red,
        "blue_probabilities": blue,
        "red_top100": top_red_combinations(red),
        "blue_top1": int(np.argmax(blue)) + 1,
        "ranking_score": "sum_of_marginal_log_odds_not_joint_probability",
    }
    counts = np.ones(16, dtype=np.float64)
    for row in rows:
        counts[row["blue"] - 1] += 1
    probabilities = (counts / counts.sum()).tolist()
    red_counts = (vectors(rows)[:, :33].sum(axis=0) + 1) / (len(rows) + 2)
    rng = random.Random(recipe.seed)
    random_red = set()
    while len(random_red) < 100:
        random_red.add(tuple(sorted(rng.sample(range(1, 34), 6))))
    return result, {
        "blue_top1": int(np.argmax(probabilities)) + 1,
        "blue_probabilities": probabilities,
        "red_top100": top_red_combinations(red_counts.tolist()),
        "random_red_top100": [list(c) for c in sorted(random_red)],
        "random_red_seed": recipe.seed,
        "recipe": "past-frequency+Laplace(1)",
    }
