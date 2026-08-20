"""Three-way market outlook from skill fit and layoff/job saturation."""

from __future__ import annotations

from typing import Literal

MarketVerdict = Literal["good", "bad", "worse"]

# Higher market_score = stronger personal demand vs supply for your skills.
FIT_GOOD_MIN = 58.0
FIT_BAD_MIN = 42.0

# Lower saturation_ratio = fewer layoffs per open role (less crowded market).
SATURATION_GOOD_MAX = 6.0
SATURATION_BAD_MAX = 18.0

VERDICT_LABELS = {
    "good": "GOOD",
    "bad": "BAD",
    "worse": "WORSE",
}

VERDICT_SUMMARY = {
    "good": (
        "Your skills match active demand and layoff saturation is manageable — "
        "favorable conditions to apply."
    ),
    "bad": (
        "Mixed market — decent skill fit or saturation, but not both. "
        "Be selective and upskill gaps."
    ),
    "worse": (
        "Weak fit or heavy layoff saturation — many candidates competing for "
        "fewer matching roles right now."
    ),
}


def _fit_band(market_score: float) -> int:
    if market_score >= FIT_GOOD_MIN:
        return 2
    if market_score >= FIT_BAD_MIN:
        return 1
    return 0


def _saturation_band(saturation_ratio: float) -> int:
    if saturation_ratio < SATURATION_GOOD_MAX:
        return 2
    if saturation_ratio < SATURATION_BAD_MAX:
        return 1
    return 0


def market_verdict(market_score: float, saturation_ratio: float) -> tuple[MarketVerdict, str]:
    """
    Classify outlook using both signals. Both must be healthy for GOOD;
    either weak signal pulls to BAD; both weak → WORSE.
    """
    fit = _fit_band(market_score)
    saturation = _saturation_band(saturation_ratio)
    weakest = min(fit, saturation)

    if weakest >= 2:
        verdict: MarketVerdict = "good"
    elif weakest == 1:
        verdict = "bad"
    else:
        verdict = "worse"

    detail = (
        f"{VERDICT_SUMMARY[verdict]} "
        f"(market fit {market_score:.0f}%, saturation {saturation_ratio:.1f}×)."
    )
    return verdict, detail
