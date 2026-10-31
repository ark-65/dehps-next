"""Finite, feedback-ranked recipe exploration between bounded local-model reasoning calls."""

import math
from itertools import product

from psycopg.types.json import Jsonb

from .errors import DomainError
from .research_policy import train_policy


def novel_specs(db, dataset, code, topic):
    from .research_memory import untried_specs

    # Progress from local structure to longer histories and stronger shrinkage.
    curricula = [
        ([8, 16, 32], [64, 128], [12, 28], [0.0005, 0.002, 0.005], [0.001, 0.01], [128, 256]),
        ([8, 16, 32, 48], [64, 128], [28, 40], [0.0005, 0.001, 0.002], [0.001, 0.01], [512, 1024]),
        ([4, 12, 24, 48, 64], [32, 64], [20, 40], [0.0002, 0.001], [0.01, 0.1], [256, 512]),
    ]
    for dimensions in curricula:
        specs = []
        for method, window, hidden, epochs, rate, decay, history in product(
            topic.get("methods", ["fft", "ridge", "newton"]), *dimensions
        ):
            spec = {
                "method": method,
                "window": window,
                "hidden": hidden,
                "epochs": epochs,
                "learning_rate": rate,
                "weight_decay": decay,
                "train_history": history,
            }
            specs.append(spec)
        if specs:
            fresh = untried_specs(db, dataset, specs)
            if fresh:
                return fresh[: db.settings.research_batch_size]
    return extended_specs(db, dataset, topic)


def _radical_inverse(index, base):
    result, divisor = 0.0, 1.0
    while index:
        index, digit = divmod(index, base)
        divisor *= base
        result += digit / divisor
    return result


def extended_specs(db, dataset, topic, *, minimum=1):
    """Persist each continuation batch and cursor; no repeated grid after exhaustion."""
    from .domain import digest
    from .release import numeric_identity
    from .research_memory import untried_specs

    numeric = numeric_identity()
    key = digest([dataset, numeric, topic["name"]])
    with db.pool.connection() as c, c.transaction():
        c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,740143))", (key,))
        previous = c.execute(
            """SELECT * FROM research_search_batches WHERE dataset_id=%s AND numeric_digest=%s
            AND topic=%s ORDER BY generation DESC LIMIT 1""",
            (dataset, numeric, topic["name"]),
        ).fetchone()
        carry = []
        if previous:
            fresh = untried_specs(db, dataset, previous["candidates"], connection=c)
            if len(fresh) >= minimum:
                return fresh
            carry = fresh
        generation = previous["generation"] + 1 if previous else 1
        cursor = previous["basis"]["next_global_cursor"] if previous else 1
        seeds = c.execute(
            """SELECT spec,node_id,seq,payload->>'verdict' AS verdict FROM research_memory_events
            WHERE dataset_id=%s AND numeric_digest=%s AND kind='EVALUATION'
              AND payload->'business' IS NOT NULL
              AND payload->>'verdict' IN ('ACCEPT_IMPROVEMENT','INCONCLUSIVE')
            ORDER BY (payload->>'verdict'='ACCEPT_IMPROVEMENT') DESC,seq DESC LIMIT 8""",
            (dataset, numeric),
        ).fetchall()
        parent = c.execute(
            "SELECT champion_spec FROM research_programs WHERE last_dataset=%s AND champion_spec IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
            (dataset,),
        ).fetchone()
        anchors = ([parent["champion_spec"]] if parent else []) + [s["spec"] for s in seeds]
        if not anchors:
            from .research import ROOT_SPEC

            anchors = [ROOT_SPEC]
        methods = topic.get("methods", ["fft", "ridge", "newton"])
        neighbors = []
        for i in range(512):
            spec = dict(anchors[i % len(anchors)])
            spec["method"] = methods[(i // len(anchors)) % len(methods)]
            parameter = ("window", "hidden", "epochs", "learning_rate", "weight_decay", "train_history")[
                (i // 2) % 6
            ]
            direction = 1 if i % 2 else -1
            scale = 1 + (generation - 1) % 8
            value = spec[parameter]
            if parameter == "learning_rate":
                value = round(min(0.1, max(0.00001, value * 2 ** (direction * scale / 8))), 8)
            elif parameter == "weight_decay":
                value = round(min(1.0, max(0.0, value + direction * 0.0001 * scale)), 8)
            else:
                low, high, step = {
                    "window": (2, 64, 1),
                    "hidden": (8, 256, 8),
                    "epochs": (1, 200, 1),
                    "train_history": (64, 1024, 16),
                }[parameter]
                value = max(low, min(high, value + direction * step * scale))
            spec[parameter] = value
            neighbors.append(spec)
        batch_size = db.settings.research_batch_size
        neighbors = untried_specs(db, dataset, neighbors, connection=c)[: batch_size // 2]
        candidates = list(carry)
        for spec in neighbors:
            if spec not in candidates:
                candidates.append(spec)
        candidates = candidates[:batch_size]
        neighbor_count = len(candidates) - len(carry)
        initial_count = len(candidates)
        seen = {digest(s) for s in candidates}
        while len(candidates) < batch_size:
            global_specs = []
            for index in range(cursor, cursor + 512):
                u = [_radical_inverse(index, p) for p in (2, 3, 5, 7, 11, 13, 17)]
                global_specs.append(
                    {
                        "method": methods[min(len(methods) - 1, int(u[0] * len(methods)))],
                        "window": 2 + int(u[1] * 63),
                        "hidden": 8 * (1 + int(u[2] * 32)),
                        "epochs": 1 + int(u[3] * 200),
                        "learning_rate": round(math.exp(math.log(0.00001) + u[4] * math.log(10000)), 8),
                        "weight_decay": round(u[5] ** 3, 8),
                        "train_history": 64 + int(u[6] * 961),
                    }
                )
            cursor += 512
            for spec in untried_specs(db, dataset, global_specs, connection=c):
                identity = digest(spec)
                if identity not in seen:
                    candidates.append(spec)
                    seen.add(identity)
                if len(candidates) == batch_size:
                    break
        basis = {
            "policy": "feedback-neighbors-and-halton-v1",
            "neighbor_count": neighbor_count,
            "global_count": batch_size - initial_count,
            "carried_untried": len(carry),
            "feedback": seeds,
            "anchors": anchors,
            "next_global_cursor": cursor,
            "evidence": "NEW_UNTRAINED_CANDIDATES;NOT_NEW_FITS_OR_PROGRESS",
        }
        c.execute(
            """INSERT INTO research_search_batches(dataset_id,numeric_digest,topic,generation,candidates,basis)
            VALUES(%s,%s,%s,%s,%s,%s)""",
            (dataset, numeric, topic["name"], generation, Jsonb(candidates), Jsonb(basis)),
        )
        return candidates


def propose_adaptive(campaign, nodes, pulse, db, artifacts, job):
    selected = next(n for n in nodes if n["id"] == campaign["selected_node"])
    topic = campaign["config"].get("topic") or {"methods": ["fft", "ridge", "newton"]}
    specs = novel_specs(db, campaign["dataset_id"], campaign["config"]["code_digest"], topic)
    if not specs:
        raise DomainError("SEARCH_SPACE_EXHAUSTED", "Finite causal recipe grid exhausted")
    # Reuse unchosen ideas generated by the local model before broadening its direction.
    ideas = [idea for node in nodes for idea in node["hypothesis"].get("candidates", [])]
    from .research_memory import known_specs

    tried = known_specs(db, campaign["dataset_id"])
    for idea in ideas:
        if idea["spec"] not in specs and idea["spec"] not in tried:
            specs.append(idea["spec"])
    pulse()
    value, policy = train_policy(db, artifacts, campaign, job)
    ranked = sorted(specs, key=lambda s: value(s, selected["evaluation"]["summary"]), reverse=True)
    chosen = ranked[0]
    return {
        "source": "TRAINED_DIRECTION_VALUE_NETWORK",
        "spec": chosen,
        "hypothesis": "Reconsider local-model ideas and change bounded window, architecture or shrinkage using observed replay rewards.",
        "falsification": "Reject regression on the same recent100, tail10 and stratified historical list; restore the parent anchor.",
        "direction_value_model": policy,
        "novel_candidates": len(ranked),
        "estimated_development_reward": value(chosen, selected["evaluation"]["summary"]),
        "execution_note": "No additional Qwen request in this step; neural direction-value and predictor fitting continue under hardware safeguards.",
    }
