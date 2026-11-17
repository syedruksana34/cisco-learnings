"""Priority score calculation for monitoring alerts."""

_SEVERITY_WEIGHTS = {"critical": 60, "warning": 30, "info": 10}


def calculate_priority_score(severity: str, metric_value: float, threshold: float) -> int:
    """Return a 0-100 priority score combining severity and threshold breach."""
    if severity not in _SEVERITY_WEIGHTS:
        raise ValueError(f"Unsupported severity: {severity!r}")
    if threshold == 0:
        raise ValueError("threshold must not be zero")
    percent_over_threshold = max(0.0, (metric_value - threshold) / abs(threshold))
    bonus = min(40, int(percent_over_threshold * 40))
    return _SEVERITY_WEIGHTS[severity] + bonus
