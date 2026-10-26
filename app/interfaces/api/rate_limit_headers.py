
from app.application.ports.rate_limiter import RateLimitDecision


def rate_limit_headers(decision: RateLimitDecision) -> dict[str, str]:
    """Return RateLimit-Policy and RateLimit values for this decision."""
    policy_items = [
        f'"{policy.name}";q={policy.quota};w={policy.window_seconds};qu="requests"'
        for policy in decision.policies
    ]
    limit_items = [
        f'"{policy.name}";r={policy.remaining};t={policy.reset_seconds}'
        for policy in decision.policies
    ]
    return {
        "RateLimit-Policy": ",".join(policy_items),
        "RateLimit": ",".join(limit_items),
    }
