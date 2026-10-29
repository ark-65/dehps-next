"""Versioned, bounded numerical tools; no code execution from model output."""

import math

import numpy as np

from .errors import DomainError


def temperature_newton(logits, labels):
    """Damped Newton/backtracking on log temperature, using prior calibration labels."""
    logits = np.asarray(logits, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.int64)

    def objective(eta):
        u = logits * math.exp(-eta)
        u -= u.max(axis=1, keepdims=True)
        exp = np.exp(u)
        p = exp / exp.sum(axis=1, keepdims=True)
        loss = float(np.mean(np.log(exp.sum(axis=1)) - u[np.arange(len(u)), labels]))
        centered = u - (p * u).sum(axis=1, keepdims=True)
        gradient = float(np.mean(u[np.arange(len(u)), labels] - (p * u).sum(axis=1)))
        hessian = float(np.mean((p * centered**2).sum(axis=1))) - gradient
        return loss, gradient, hessian

    eta = 0.0
    initial = objective(eta)[0]
    steps = 0
    for _ in range(12):
        loss, gradient, hessian = objective(eta)
        step = float(np.clip(gradient / max(abs(hessian), 0.05), -1, 1))
        accepted = False
        for power in range(8):
            candidate = float(np.clip(eta - step * 0.5**power, math.log(0.5), math.log(10)))
            if objective(candidate)[0] <= loss:
                eta = candidate
                accepted = True
                steps += 1
                break
        if not accepted or abs(gradient) < 1e-7:
            break
    return {
        "temperature": math.exp(eta),
        "newton_steps": steps,
        "prior_calibration_loss_before": initial,
        "prior_calibration_loss_after": objective(eta)[0],
    }


def run_tool(method):
    """Numerical sanity probes demonstrate mechanics, never predictive performance."""
    if method == "fft":
        t = np.arange(64)
        signal = np.sin(2 * np.pi * t / 32)
        observed = signal + 0.2 * np.sin(2 * np.pi * t / 4)
        spectrum = np.fft.rfft(observed)
        spectrum[4:] = 0
        recovered = np.fft.irfft(spectrum, n=64)
        result = {
            "tool": "numpy.rfft/irfft",
            "known_signal_mse_before": float(np.mean((observed - signal) ** 2)),
            "known_signal_mse_after": float(np.mean((recovered - signal) ** 2)),
            "limitation": "A known sinusoid does not establish a period in lottery labels",
        }
    elif method == "ridge":
        x = np.column_stack([np.arange(8) / 8, np.ones(8)])
        y = 2 * x[:, 0] + 0.5
        coefficients = np.linalg.solve(x.T @ x + np.eye(2) * 0.1, x.T @ y)
        result = {
            "tool": "numpy.linalg.solve",
            "coefficients": coefficients.tolist(),
            "normal_equation_residual": float(
                np.linalg.norm((x.T @ x + np.eye(2) * 0.1) @ coefficients - x.T @ y)
            ),
            "limitation": "Regularization introduces bias; residual head must pass causal replay",
        }
    elif method == "newton":
        logits = np.array([[4.0, 0.0], [4.0, 0.0], [0.0, 4.0], [0.0, 4.0]])
        result = {
            "tool": "damped_newton_log_temperature",
            **temperature_newton(logits, np.array([0, 1, 0, 1])),
            "limitation": "Prior calibration can reduce overconfidence without improving Top1",
        }
    else:
        raise DomainError("UNKNOWN_MATH_TOOL", "Method is outside the accepted tool registry")
    return {"method": method, "version": 1, "evidence": "NUMERICAL_SANITY_ONLY", **result}
