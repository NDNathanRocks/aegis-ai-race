"""Token estimation and the simulated enterprise cost model.

Cost = tokens / 1e6 * $15, scaled by a per-tier multiplier: the 8B tier costs
1/15th of the 70B tier per token (configurable). Token counts are estimates (~4 chars/token) unless the
provider reported real usage.
"""
import math
import re

from app.schemas import Tier, TokenUsage, UsageSource

TIER_MULTIPLIER: dict[str, float] = {"70b": 1.0, "8b": 1 / 15}
_WORD = re.compile(r"\w+|[^\w\s]")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    by_chars = math.ceil(len(text) / 4)
    by_words = math.ceil(len(_WORD.findall(text)) * 0.9)
    return max(1, round((by_chars + by_words) / 2))


def cost_usd(tokens: int, tier: Tier, usd_per_million: float = 15.0, ratio_8b: float | None = None) -> float:
    mult = TIER_MULTIPLIER[tier] if ratio_8b is None or tier == "70b" else ratio_8b
    return tokens / 1_000_000 * usd_per_million * mult


def make_usage(
    prompt_tokens: int,
    completion_tokens: int,
    tier: Tier,
    usd_per_million: float = 15.0,
    source: UsageSource = "estimate",
    ratio_8b: float | None = None,
) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        tier=tier,
        cost_usd=cost_usd(prompt_tokens + completion_tokens, tier, usd_per_million, ratio_8b),
        source=source,
    )
