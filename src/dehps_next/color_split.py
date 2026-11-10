"""Versioned output composition: retain the frozen red procedure, vary blue only."""

from .errors import DomainError
from .model import encode_torch

VERSION = "retained-red-blue-specialist-v1"
CALIBRATED_VERSION = "retained-red-blue-specialist-mass6-v2"
BASE_METHODS = ("raw", "fft", "ridge", "newton")
ORIGINAL_METHODS = tuple("split_blue_" + m + "_v1" for m in BASE_METHODS)
CALIBRATED_METHODS = tuple("mass6_blue_" + m + "_v2" for m in BASE_METHODS)
METHODS = ORIGINAL_METHODS + CALIBRATED_METHODS
RED_SPEC = {"method": "ridge", "window": 48, "hidden": 64, "epochs": 40,
            "learning_rate": 0.00054525, "weight_decay": 0.01, "train_history": 512}
TOPIC = {"name": "color-separated-specialists-v1", "methods": list(ORIGINAL_METHODS),
         "question": "Can separately fitted blue experts retain measured blue gains without sacrificing the frozen red procedure?"}
CALIBRATED_TOPIC = {"name": "red-cardinality-specialists-v2", "methods": list(CALIBRATED_METHODS),
                    "question": "Preserve retained red rankings and blue improvements while enforcing the known six-red probability mass"}


def is_split(spec):
    return spec["method"] in METHODS


def blue_spec(spec):
    method = BASE_METHODS[METHODS.index(spec["method"]) % len(BASE_METHODS)]
    return {**spec, "method": method}


def wrap(spec, *, calibrated=False):
    if spec["method"] not in BASE_METHODS:
        raise DomainError("SPECIALIST_COMPONENT", "Only audited base fitters may be composed")
    methods = CALIBRATED_METHODS if calibrated else ORIGINAL_METHODS
    return {**spec, "method": methods[BASE_METHODS.index(spec["method"])]}


def is_calibrated(spec):
    return spec["method"] in CALIBRATED_METHODS


def steps(spec):
    return RED_SPEC["epochs"] + spec["epochs"] if is_split(spec) else spec["epochs"]


def fit(prior, spec, seed, pulse, initial=None):
    from .research_compute import fit_prior, state_hash

    # Both components start fresh, matching every historical-origin procedure.
    # Never warm-start the retained red output from a rejected child's encoder.
    red, _, r = fit_prior(prior, RED_SPEC, seed, pulse)
    _, blue, b = fit_prior(prior, blue_spec(spec), seed, pulse)
    version = CALIBRATED_VERSION if is_calibrated(spec) else VERSION
    models = {"red": r["model"], "blue": b["model"]}
    optimizers = {"red": r["optimizer"], "blue": b["optimizer"]}
    mathematical = {"version": version, "red_spec": RED_SPEC,
                    "red": r["mathematical"], "blue": b["mathematical"]}
    if is_calibrated(spec):
        from .red_cardinality import CONTRACT, calibrate
        red = calibrate(red)
        mathematical["red_calibration"] = CONTRACT
    payload = {"model_type": version, "spec": spec, "model": models,
               "optimizer": optimizers, "components": {"red": r, "blue": b},
               "rng": b["rng"], "inherited": False, "seed": seed,
               "gradient_steps": r["gradient_steps"] + b["gradient_steps"],
               "model_state_digest": state_hash(models),
               "weight_digest": state_hash({"red": r["weight_digest"], "blue": b["weight_digest"]}),
               "initial_weight_digest": state_hash({"red": r["initial_weight_digest"],
                                                     "blue": b["initial_weight_digest"]}),
               "optimizer_digest": state_hash(optimizers), "mathematical": mathematical,
               "mathematical_digest": state_hash(mathematical),
               "component_parameters_updated": all(x["weight_digest"] != x["initial_weight_digest"] for x in (r, b)),
               "loss": b["loss"]}
    if not payload["component_parameters_updated"]:
        raise DomainError("NO_PARAMETER_UPDATE", "Both separately fitted components must update")
    return red, blue, payload


def restore(anchor):
    from .research_compute import restore_anchor, state_hash

    version = CALIBRATED_VERSION if is_calibrated(anchor["spec"]) else VERSION
    if is_calibrated(anchor["spec"]):
        from .red_cardinality import CONTRACT
        if anchor["mathematical"].get("red_calibration") != CONTRACT:
            raise DomainError("RED_CALIBRATION_CHANGED", "The label-free cardinality contract changed")
    if (anchor["model_type"] != version or anchor["mathematical"]["version"] != version
            or set(anchor["components"]) != {"red", "blue"}
            or anchor["mathematical"]["red_spec"] != RED_SPEC
            or anchor["components"]["red"]["spec"] != RED_SPEC
            or anchor["components"]["blue"]["spec"] != blue_spec(anchor["spec"])):
        raise DomainError("SPECIALIST_ANCHOR_CHANGED", "Component recipe or version changed")
    models = {k: v["model"] for k, v in anchor["components"].items()}
    opts = {k: v["optimizer"] for k, v in anchor["components"].items()}
    if (state_hash(models) != anchor["model_state_digest"] or state_hash(anchor["model"]) != anchor["model_state_digest"]
            or state_hash({k: v["weight_digest"] for k, v in anchor["components"].items()}) != anchor["weight_digest"]
            or state_hash(opts) != anchor["optimizer_digest"] or state_hash(anchor["optimizer"]) != anchor["optimizer_digest"]
            or state_hash(anchor["mathematical"]) != anchor["mathematical_digest"]
            or state_hash(anchor["rng"]) != state_hash(anchor["components"]["blue"]["rng"])):
        raise DomainError("SPECIALIST_ANCHOR_CORRUPT", "Component state digest differs")
    for component in anchor["components"].values():
        restore_anchor(encode_torch({**component, "through_issue": anchor["through_issue"]}))
    return {"weight_digest": anchor["weight_digest"], "optimizer_digest": anchor["optimizer_digest"],
            "rng_restored": True, "rng_digest": state_hash(anchor["rng"]),
            "mathematical_digest": anchor["mathematical_digest"], "through_issue": anchor["through_issue"]}


def predict(anchor, rows):
    from .research_compute import predict_anchor

    values = {k: predict_anchor(encode_torch({**v, "through_issue": anchor["through_issue"]}), rows)
              for k, v in anchor["components"].items()}
    version = CALIBRATED_VERSION if is_calibrated(anchor["spec"]) else VERSION
    if is_calibrated(anchor["spec"]):
        from .red_cardinality import calibrate
        from .domain import top_red_combinations
        red = calibrate(values["red"]["red_probabilities"]).tolist()
        tickets = top_red_combinations(red)
        if tickets != values["red"]["red_top100"]:
            raise DomainError("RED_CALIBRATION_RANK_CHANGED", "The canonical redTop100 must remain identical")
        values["red"] = {**values["red"], "red_probabilities": red, "red_top100": tickets}
    return {**values["red"], "blue_probabilities": values["blue"]["blue_probabilities"],
            "blue_top1": values["blue"]["blue_top1"], "model_type": version,
            "feature_version": version}
