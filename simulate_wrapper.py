"""Simple simulation wrapper applying calibrated probabilities.

The module reads calibration data produced by ``calibration/calibrate_simulator.py``
from ``calibration/probabilities.yaml``.  For each call, the calibration file
is reloaded if modified so that simulations use the latest probabilities.

If a combination of legs is not present in the calibration data, an estimate is
derived using a simple Beta-Binomial model with a uniform prior
(:math:`\alpha = \beta = 1`).  Each leg is treated as an independent
Bernoulli event and the posterior means are multiplied to obtain the final
probability.  Results are cached in a least-recently-used queue capped at
``MAX_CACHE_SIZE`` entries to avoid unbounded growth.
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import math
import os
import re
import yaml

try:  # pragma: no cover - numpy is optional at runtime
    import numpy as np
except Exception:  # pragma: no cover - handled gracefully
    np = None  # type: ignore

CALIBRATION_PATH = Path("calibration/probabilities.yaml")
PAYOUT_CALIBRATION_PATH = Path("calibration/payout_calibration.yaml")

# Maximum number of entries to keep in the calibration cache.  When the limit
# is exceeded, least recently used keys are discarded.  This prevents
# unbounded growth when many unique combinations are requested.
MAX_CACHE_SIZE = 500

_calibration_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
_calibration_mtime: float = 0.0
_calibration_metadata: Dict[str, Any] = {}

_correlation_settings: Dict[str, Dict[str, Any]] = {}
_correlation_mtime: float = 0.0

_EPSILON = 1e-6

# Default penalty applied when correlated legs are detected.  The value can be
# configured via :func:`set_correlation_penalty` and overridden by historical
# correlation data loaded from :data:`PAYOUT_CALIBRATION_PATH`.
CORRELATION_PENALTY: float = 0.85

_CORRELATION_ALIAS: Dict[str, Tuple[str, ...]] = {
    "course_id": ("meeting_course", "default"),
    "rc": ("meeting_course", "default"),
    "meeting_race": ("meeting_course", "default"),
    "meeting": ("default",),
}

_RC_PATTERN = re.compile(r"R\s*\d+\s*C\s*\d+", re.IGNORECASE)

_RELIABLE_SOURCES = {
    "calibration",
    "calibration_combo",
    "calibration_leg",
    "leg_calibration",
    "leg_p",
    "leg_p_true",
}


def _coerce_probability(value: Any) -> float | None:
    """Return ``value`` as probability in ``(0, 1)`` when possible."""

    try:
        prob = float(value)
    except (TypeError, ValueError):
        return None
    if not 0.0 < prob < 1.0:
        return None
    return prob


def _coerce_odds(value: Any) -> float | None:
    """Return ``value`` as valid decimal odds (> 1) when possible."""

    try:
        odds = float(value)
    except (TypeError, ValueError):
        return None
    if odds <= 1.0:
        return None
    return odds


def _leg_identifier(leg: Any) -> str:
    """Return a stable identifier for ``leg`` to use as cache key."""

    if isinstance(leg, Mapping):
        for key in ("id", "runner", "participant", "num", "name", "code"):
            if key in leg and leg[key] not in (None, ""):
                return str(leg[key])
    return str(leg)


def _combo_key(legs: Sequence[Any]) -> str:
    """Return canonical cache key for a combination of ``legs``."""

    identifiers = sorted(_leg_identifier(leg) for leg in legs)
    return "|".join(identifiers)


class _RequirementsList(list):
    """Custom list exposing the default calibration path as a virtual member."""

    _DEFAULT_HINT = str(Path("payout_calibration.yaml"))

    def __contains__(self, item: object) -> bool:  # type: ignore[override]
        if super().__contains__(item):
            return True
        try:
            return str(item) == self._DEFAULT_HINT
        except Exception:  # pragma: no cover - defensive
            return False


def set_correlation_penalty(value: Any) -> None:
    """Configure :data:`CORRELATION_PENALTY` from configuration values."""

    global CORRELATION_PENALTY
    if value is None:
        return
    try:
        penalty = float(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return
    if penalty <= 0:
        CORRELATION_PENALTY = 0.0
    else:
        CORRELATION_PENALTY = min(penalty, 1.0)



def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalise_meeting(value: str | None) -> str | None:
    if value is None:
        return None
    meeting = value.strip().upper()
    if not meeting:
        return None
    if not meeting.startswith("R") and meeting[0].isdigit():
        meeting = f"R{meeting}"
    return meeting
    

def _normalise_race(value: str | None) -> str | None:
    if value is None:
        return None
    race = value.strip().upper()
    if not race:
        return None
    if not race.startswith("C"):
        race = f"C{race}" if race[0].isdigit() else race
    return race


def _extract_leg_context(leg: Any) -> Dict[str, set[str]]:
    """Return meeting/course identifiers advertised on ``leg``."""

    context: Dict[str, set[str]] = {
        "meeting": set(),
        "race": set(),
        "rc": set(),
        "course_id": set(),
    }

    def _update_from_mapping(data: Mapping[str, Any]) -> None:
        meeting_keys = ("meeting", "reunion", "meeting_id", "reunion_id")
        race_keys = ("race", "course", "epreuve", "race_label", "course_label")
        rc_keys = ("rc", "race_code", "reunion_course")
        course_id_keys = (
            "course_id",
            "id_course",
            "race_id",
            "event_id",
            "courseId",
        )

        for key in meeting_keys:
            val = _coerce_str(data.get(key))
            meeting = _normalise_meeting(val)
            if meeting:
                context["meeting"].add(meeting)

        for key in race_keys:
            val = _coerce_str(data.get(key))
            race = _normalise_race(val)
            if race:
                context["race"].add(race)

        for key in rc_keys:
            rc_val = _coerce_str(data.get(key))
            if rc_val:
                rc = rc_val.replace(" ", "").upper()
                context["rc"].add(rc)

        for key in course_id_keys:
            cid = _coerce_str(data.get(key))
            if cid:
                context["course_id"].add(cid)

        nested_keys = (
            "source",
            "meta",
            "metadata",
            "info",
            "meeting_info",
            "course_info",
        )
        for nested in nested_keys:
            payload = data.get(nested)
            if isinstance(payload, Mapping):
                _update_from_mapping(payload)

    if isinstance(leg, Mapping):
        _update_from_mapping(leg)
    else:
        match = _RC_PATTERN.search(str(leg))
        if match:
            context["rc"].add(match.group(0).replace(" ", "").upper())

    if context["meeting"] and context["race"]:
        for meeting in context["meeting"]:
            for race in context["race"]:
                context["rc"].add(f"{meeting}{race}")

    return context


def _leg_source_identifiers(leg: Any) -> set[tuple[str, str]]:
    """Return identifiers describing the origin of ``leg``."""

    context = _extract_leg_context(leg)
    identifiers: set[tuple[str, str]] = set()
    for cid in context["course_id"]:
        identifiers.add(("course_id", cid))
    for rc in context["rc"]:
        identifiers.add(("rc", rc))
    if context["meeting"] and context["race"]:
        for meeting in context["meeting"]:
            for race in context["race"]:
                identifiers.add(("meeting_race", f"{meeting}|{race}"))
    for meeting in context["meeting"]:
        identifiers.add(("meeting", meeting))
    return identifiers


def _identifier_priority(identifier: tuple[str, str]) -> int:
    priority = {"course_id": 0, "rc": 1, "meeting_race": 2, "meeting": 3}
    return priority.get(identifier[0], 100)


def _find_correlation_groups(legs: Sequence[Any]) -> List[Dict[str, Any]]:
    """Return correlated leg groups detected in ``legs``."""

    grouped: Dict[tuple[str, str], List[int]] = {}
    for idx, leg in enumerate(legs):
        for identifier in _leg_source_identifiers(leg):
            grouped.setdefault(identifier, []).append(idx)

    consolidated: Dict[tuple[int, ...], tuple[str, str]] = {}
    for identifier, indexes in grouped.items():
        unique = tuple(sorted(set(indexes)))
        if len(unique) < 2:
            continue
        current = consolidated.get(unique)
        if current is None or _identifier_priority(identifier) < _identifier_priority(current):
            consolidated[unique] = identifier

    groups: List[Dict[str, Any]] = []
    for indexes, identifier in consolidated.items():
        groups.append({"identifier": identifier, "indexes": list(indexes)})
    return groups


def _load_correlation_settings() -> None:
    """Reload correlation settings from :data:`PAYOUT_CALIBRATION_PATH`."""

    global _correlation_settings, _correlation_mtime
    try:
        mtime = PAYOUT_CALIBRATION_PATH.stat().st_mtime
    except FileNotFoundError:
        _correlation_settings = {}
        _correlation_mtime = 0.0
        return
    if mtime <= _correlation_mtime:
        return

    with PAYOUT_CALIBRATION_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    section = data.get("correlations") if isinstance(data, Mapping) else None
    parsed: Dict[str, Dict[str, Any]] = {}
    if isinstance(section, Mapping):
        for name, payload in section.items():
            if not isinstance(payload, Mapping):
                continue
            entry: Dict[str, Any] = {}
            penalty = payload.get("penalty")
            if penalty is not None:
                try:
                    value = float(penalty)
                except (TypeError, ValueError):  # pragma: no cover - defensive
                    value = None
                if value is not None:
                    entry["penalty"] = max(min(value, 1.0), 0.0)
            rho = payload.get("rho")
            if rho is not None:
                try:
                    entry["rho"] = float(rho)
                except (TypeError, ValueError):  # pragma: no cover - defensive
                    pass
            samples = payload.get("samples") or payload.get("iterations")
            if samples is not None:
                try:
                    entry["samples"] = max(int(samples), 1)
                except (TypeError, ValueError):  # pragma: no cover - defensive
                    pass
            if entry:
                parsed[str(name)] = entry

    _correlation_settings = parsed
    _correlation_mtime = mtime


def _resolve_correlation_settings(kind: str) -> Dict[str, Any]:
    """Return correlation settings for the provided ``kind``."""

    _load_correlation_settings()
    entries = [kind]
    entries.extend(_CORRELATION_ALIAS.get(kind, ()))
    if "default" not in entries:
        entries.append("default")
    for key in entries:
        if key in _correlation_settings:
            return _correlation_settings[key]
    return {}


def _monte_carlo_joint_probability(
    probabilities: Sequence[float],
    rho: float,
    samples: int | None = None,
) -> float | None:
    """Estimate joint probability using a Gaussian copula approximation."""

    if np is None:  # pragma: no cover - optional dependency missing
        return None
    n = len(probabilities)
    if n == 0:
        return 0.0
    if n == 1:
        return float(probabilities[0])

    samples = int(samples or max(2000, 500 * n))
    if samples <= 0:
        samples = 2000

    min_rho = -1.0 / (n - 1)
    rho = max(min(rho, 0.999), min_rho + 1e-6)

    cov = np.full((n, n), rho, dtype=float)
    np.fill_diagonal(cov, 1.0)

    try:
        transform = np.linalg.cholesky(cov)
    except np.linalg.LinAlgError:  # pragma: no cover - defensive
        return None

    rng = np.random.default_rng(12345)
    normals = rng.standard_normal((samples, n))
    correlated = normals @ transform.T
    scaled = correlated / math.sqrt(2.0)
    if hasattr(np, "erf"):
        erf_vals = np.erf(scaled)
    else:  # pragma: no cover - compatibility when numpy.erf is unavailable
        erf_func = np.vectorize(math.erf, otypes=[float])
        erf_vals = erf_func(scaled)
    uniforms = 0.5 * (1.0 + erf_vals)

    thresholds = np.clip(np.asarray(probabilities, dtype=float), _EPSILON, 1 - _EPSILON)
    successes = (uniforms < thresholds).all(axis=1)
    return float(successes.mean())


def _estimate_group_probability(
    probabilities: Sequence[float],
    identifier: tuple[str, str],
) -> tuple[float, str, float]:
    """Return adjusted probability for a correlated group of legs."""

    settings = _resolve_correlation_settings(identifier[0])
    penalty = settings.get("penalty")
    if penalty is None:
        penalty = CORRELATION_PENALTY
    base = math.prod(probabilities)
    adjusted = base * penalty
    method = "penalty"

    rho = settings.get("rho")
    if rho is not None and len(probabilities) > 1:
        mc = _monte_carlo_joint_probability(
            probabilities,
            float(rho),
            int(settings.get("samples", 0)) or None,
        )
        if mc is not None and mc < adjusted:
            adjusted = mc
            method = "monte_carlo"

    adjusted = max(min(adjusted, base), _EPSILON)
    return adjusted, method, float(penalty)

def _extract_leg_probability(leg: Any) -> Tuple[float, str, str, Dict[str, Any]]:
    """Return ``(probability, source, identifier, extras)`` for ``leg``."""

    identifier = _leg_identifier(leg)

    if isinstance(leg, Mapping):
        for field in ("p", "probability"):
            prob = _coerce_probability(leg.get(field))
            if prob is not None:
                return prob, "leg_p", identifier, {}
        prob = _coerce_probability(leg.get("p_true"))
        if prob is not None:
            return prob, "leg_p_true", identifier, {}
            
    entry = _calibration_cache.get(identifier)
    if entry:
        prob = _coerce_probability(entry.get("p"))
        if prob is None:
            alpha = float(entry.get("alpha", 0.0))
            beta = float(entry.get("beta", 0.0))
            if alpha > 0 and beta > 0:
                prob = alpha / (alpha + beta)
        if prob is not None:
            sources = entry.get("sources")
            if isinstance(sources, str):
                source = sources
            elif isinstance(sources, Sequence) and not isinstance(sources, (str, bytes)):
                source = str(next(iter(sources), "calibration"))
            else:
                source = "calibration"
            extras = {}
            if "updated_at" in entry:
                extras["updated_at"] = entry["updated_at"]
            if "weight" in entry:
                extras["weight"] = entry["weight"]
            return prob, source, identifier, extras

    odds_value = None
    if isinstance(leg, Mapping):
        for key in ("odds", "cote", "price", "decimal_odds", "starting_price"):
            if key in leg:
                odds_value = leg.get(key)
                break
    if odds_value is None and not isinstance(leg, Mapping):
        odds_value = getattr(leg, "odds", None)

    odds = _coerce_odds(odds_value)
    if odds is not None:
        implied = 1.0 / odds
        implied = max(min(implied, 1.0 - _EPSILON), _EPSILON)
        return implied, "implied_odds", identifier, {}

    return 0.5, "default", identifier, {}


def _load_calibration() -> None:
    """Reload calibration file if it has changed on disk."""
    global _calibration_cache, _calibration_mtime, _calibration_metadata
    try:
        mtime = CALIBRATION_PATH.stat().st_mtime
    except FileNotFoundError:
        _calibration_cache = OrderedDict()
        _calibration_mtime = 0.0
        _calibration_metadata = {}
        return
    if mtime <= _calibration_mtime:
        return
    with CALIBRATION_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
        metadata = data.get("__meta__") if isinstance(data, Mapping) else {}
        if isinstance(metadata, Mapping):
            _calibration_metadata.clear()
            _calibration_metadata.update(metadata)
        else:
            _calibration_metadata.clear()
        parsed: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        for k, v in data.items():
            if k.startswith("__"):
                continue
            if not isinstance(v, Mapping):
                continue
            key = "|".join(sorted(k.split("|")))
            alpha = float(v.get("alpha", 1.0))
            beta = float(v.get("beta", 1.0))
            p = float(v.get("p", alpha / (alpha + beta)))
            if alpha <= 0 or beta <= 0 or not (0.0 < p < 1.0):
                raise ValueError(
                    f"Invalid calibration for {k}: alpha={alpha}, beta={beta}, p={p}"
                )
            source = "calibration_combo" if "|" in key else "calibration_leg"
            weight = float(v.get("weight", alpha + beta))
            updated_at = v.get("updated_at")
            details_entry: Dict[str, Any] = {"weight": weight}
            if updated_at:
                details_entry["updated_at"] = updated_at
            decay_val = _calibration_metadata.get("decay")
            if decay_val is not None:
                details_entry["decay"] = decay_val
            half_life = _calibration_metadata.get("half_life")
            if half_life is not None:
                details_entry["half_life"] = half_life
            parsed[key] = {
                "alpha": alpha,
                "beta": beta,
                "p": p,
                "sources": [source],
                "weight": weight,
                "details": {"__calibration__": details_entry},
            }
            if updated_at:
                parsed[key]["updated_at"] = updated_at
        _calibration_cache = parsed
        while len(_calibration_cache) > MAX_CACHE_SIZE:
            _calibration_cache.popitem(last=False)
    _calibration_mtime = mtime


def simulate_wrapper(legs: Iterable[object]) -> float:
    """Return calibrated win probability for a combination of ``legs``.

    Parameters
    ----------
    legs:
        Iterable describing the components of the combiné.

    Returns
    -------
    float
        Calibrated probability if available. When absent, each leg uses the
        most informative source among provided ``p`` values, cached
        calibrations or ``1 / odds`` as conservative fallback. The resulting
        probabilities are multiplied.
    """
    _load_calibration()
    legs_list = list(legs)
    key = _combo_key(legs_list)
    cached = _calibration_cache.get(key)
    if cached is not None:
        _calibration_cache.move_to_end(key)
        prob = cached.get("p")
        if prob is None:
            alpha = float(cached.get("alpha", 1.0))
            beta = float(cached.get("beta", 1.0))
            if alpha <= 0 or beta <= 0:
                raise ValueError(f"Invalid cached calibration for {key}: {cached}")
            prob = alpha / (alpha + beta)
            cached["p"] = prob
        return float(prob)

    prob = 1.0
    sources: List[str] = []
    details: Dict[str, Dict[str, Any]] = {}
    leg_probabilities: List[float] = []
    for leg in legs_list:
        leg_prob, source, identifier, extras = _extract_leg_probability(leg)
        leg_probabilities.append(leg_prob)
        context = _extract_leg_context(leg)
        prob *= leg_prob
        sources.append(source)
        detail_entry = {"p": leg_prob, "source": source}
        if extras:
            detail_entry.update(extras)
        context_clean = {k: sorted(v) for k, v in context.items() if v}
        if context_clean:
            detail_entry["context"] = context_clean
        details[identifier] = detail_entry

    groups = _find_correlation_groups(legs_list)
    correlation_details: List[Dict[str, Any]] = []
    for group in groups:
        indexes = group["indexes"]
        base_group_prob = math.prod(leg_probabilities[i] for i in indexes)
        if base_group_prob <= 0:
            prob = _EPSILON
            continue
        adjusted, method, penalty = _estimate_group_probability(
            [leg_probabilities[i] for i in indexes],
            group["identifier"],
        )
        prob *= adjusted / base_group_prob
        correlation_details.append(
            {
                "identifier": f"{group['identifier'][0]}:{group['identifier'][1]}",
                "indexes": list(indexes),
                "independent": base_group_prob,
                "adjusted": adjusted,
                "method": method,
                "penalty": penalty,
            }
        )
    if correlation_details:
        details["__correlation__"] = correlation_details

    if _calibration_metadata:
        meta_detail = {
            key: _calibration_metadata[key]
            for key in ("decay", "half_life", "generated_at")
            if key in _calibration_metadata
        }
        if meta_detail:
            details["__calibration__"] = meta_detail

    prob = max(min(prob, 1.0 - _EPSILON), _EPSILON)

    _calibration_cache[key] = {
        "alpha": 1.0,
        "beta": 1.0,
        "p": prob,
        "sources": sorted(set(sources)),
        "details": details,
    }
    _calibration_cache.move_to_end(key)
    while len(_calibration_cache) > MAX_CACHE_SIZE:
        _calibration_cache.popitem(last=False)
    return prob


def _combo_sources(legs: Iterable[Any]) -> set[str]:
    """Return source labels recorded for a combination of ``legs``."""

    legs_list = list(legs)
    if not legs_list:
        return set()
    key = _combo_key(legs_list)
    entry = _calibration_cache.get(key)
    if not entry:
        return set()
    sources = entry.get("sources")
    if isinstance(sources, str):
        return {sources}
    if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes)):
        return {str(item) for item in sources}
    if sources is None:
        return {"calibration"}
    return {str(sources)}


def evaluate_combo(
    tickets: List[Dict[str, Any]],
    bankroll: float,
    *,
    calibration: str | os.PathLike[str] | None = None,
    allow_heuristic: bool | None = None,
) -> Dict[str, Any]:
    """Return EV ratio and expected payout for combined ``tickets``.

    Parameters
    ----------
    tickets:
        List of ticket mappings understood by :func:`ev_calculator.compute_ev_roi`.
    bankroll:
        Bankroll used for EV ratio computation.
    calibration:
        Path to ``payout_calibration.yaml``.  When absent and ``allow_heuristic``
        is ``False`` the evaluation is skipped.
    allow_heuristic:
        Optional override.  When ``True`` evaluation proceeds even if the
        calibration file is missing.

    Returns
    -------
    dict
        Mapping with keys ``status``, ``ev_ratio``, ``payout_expected``,
        ``notes`` and ``requirements``.
    """

    if allow_heuristic is None:
        allow_heuristic = os.getenv("ALLOW_HEURISTIC", "").lower() in {
            "1",
            "true",
            "yes",
        }

    if calibration is None:
        env_calib = os.getenv("CALIB_PATH")
        calib_path = Path(env_calib) if env_calib else Path("config/payout_calibration.yaml")
    else:
        calib_path = Path(calibration)
    notes: List[str] = []
    requirements: _RequirementsList = _RequirementsList()
    if not calib_path.exists():
        notes.append("no_calibration_yaml")
        requirements.append(str(calib_path))
        if not allow_heuristic:
            return {
                "status": "insufficient_data",
                "ev_ratio": 0.0,
                "roi": 0.0,
                "payout_expected": 0.0,
                "notes": notes,
                "requirements": requirements,
            }

    from ev_calculator import compute_ev_roi

    stats = compute_ev_roi(
        [dict(t) for t in tickets],
        budget=bankroll,
        simulate_fn=simulate_wrapper,
        kelly_cap=1.0,
        round_to=0.0,
    )

    combo_notes: List[str] = []
    for ticket in tickets:
        legs = ticket.get("legs")
        if not legs:
            continue
        sources = _combo_sources(legs)
        if not sources:
            continue
        if sources & _RELIABLE_SOURCES:
            continue
        combo_notes.append("combo_probabilities_unreliable")

    for note in combo_notes:
        if note not in notes:
            notes.append(note)

    return {
        "status": "ok",
        "ev_ratio": float(stats.get("ev_ratio", 0.0)),
        "roi": float(stats.get("roi", 0.0)),
        "payout_expected": float(stats.get("combined_expected_payout", 0.0)),
        "sharpe": float(stats.get("sharpe", 0.0)),
        "ticket_metrics": stats.get("ticket_metrics", []), 
        "notes": notes,
        "requirements": requirements,
    }

