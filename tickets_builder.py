import os
import logging
import os
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from simulate_ev import allocate_dutching_sp
from runner_chain import validate_exotics_with_simwrapper


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults & constants
# ---------------------------------------------------------------------------

BUDGET_CAP_EUR: float = 5.0
"""Maximum total budget allowed per course (EUR)."""

SP_SHARE: float = 0.60
"""Fraction of the budget dedicated to Single Placé tickets."""

COMBO_SHARE: float = 0.40
"""Fraction of the budget dedicated to combination tickets."""

EV_MIN_COMBO: float = 0.40
"""Minimum EV ratio required for a combination ticket to be considered."""

PAYOUT_MIN_COMBO: float = 12.0
"""Minimum expected payout (EUR) for a combination ticket."""

MAX_TICKETS: int = 2
"""Maximum number of tickets emitted (1 SP + 1 combo)."""


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_homogeneous_field(runners: Iterable[Mapping[str, Any]]) -> bool:
    """Return ``True`` when the top-4 implied probabilities are within 8 pts."""

    implied: List[float] = []
    for runner in runners:
        odds = _coerce_float(
            runner.get("odds")
            or runner.get("cote")
            or runner.get("expected_odds")
            or runner.get("closing_odds"),
            default=0.0,
        )
        if odds <= 0:
            continue
        implied.append(100.0 / odds)
    if len(implied) < 4:
        return False
    implied.sort(reverse=True)
    top_four = implied[:4]
    spread = max(top_four) - min(top_four)
    return spread < 8.0

def allow_combo(
    ev_global: float,
    roi_global: float,
    payout_est: float,
    *,
    ev_min: float | None = None,
    roi_min: float | None = None,
    payout_min: float | None = None,
    cfg: Mapping[str, Any] | None = None,
) -> bool:
    """Decide if a combo ticket can be issued based on EV, ROI and payout.

    Parameters
    ----------
    ev_global, roi_global, payout_est:
        Metrics returned by the EV simulation for the proposed ticket pack.
    ev_min, roi_min, payout_min:
        Optional thresholds overriding configuration defaults. When omitted,
        the values are resolved from ``cfg`` or fall back to module constants.
    cfg:
        Optional configuration mapping providing the thresholds used by the
        analysis pipeline.
    """
    def _resolve(value: float | None, default: float, keys: Tuple[str, ...] = ()) -> float:
        if value is not None:
            return float(value)
        if cfg is not None:
            for key in keys:
                if key in cfg:
                    try:
                        return float(cfg[key])
                    except (TypeError, ValueError):  # pragma: no cover - defensive
                        continue
        return default

    resolved_ev = _resolve(ev_min, EV_MIN_COMBO, ("EV_MIN_GLOBAL",))
    resolved_roi = _resolve(roi_min, 0.0, ("ROI_MIN_GLOBAL",))
    resolved_payout = _resolve(
        payout_min,
        PAYOUT_MIN_COMBO,
        ("MIN_PAYOUT_COMBOS", "EXOTIC_MIN_PAYOUT"),
    )

    if ev_global < resolved_ev:
        return False
    if roi_global < resolved_roi:
        return False
    if payout_est < resolved_payout:
        return False
    return True

def _normalise_legs(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        if "|" in value:
            parts = [v.strip() for v in value.split("|") if v.strip()]
        else:
            parts = [v.strip() for v in value.split(",") if v.strip()]
        return [str(p) for p in parts]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [str(v) for v in value]
    if isinstance(value, Mapping):
        return [str(v) for v in value.values()]
    return []


def _leg_lookup_key(leg: Any) -> str:
    if isinstance(leg, Mapping):
        for key in ("id", "code", "runner", "participant", "num", "name"):
            if key in leg and leg[key] not in (None, ""):
                return str(leg[key])
    return str(leg)


def _format_meeting(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    if not text.startswith("R") and text[0].isdigit():
        text = f"R{text}"
    return text


def _format_race(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    if not text.startswith("C") and text[0].isdigit():
        text = f"C{text}"
    return text


def _extract_course_context(*sources: Mapping[str, Any]) -> Dict[str, str]:
    context: Dict[str, str] = {}
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        meeting = source.get("meeting") or source.get("reunion")
        race = source.get("race") or source.get("course") or source.get("epreuve")
        rc = source.get("rc") or source.get("race_code")
        course_id = source.get("course_id") or source.get("id_course")
        if meeting and "meeting" not in context:
            formatted = _format_meeting(meeting)
            if formatted:
                context["meeting"] = formatted
        if race and "race" not in context:
            formatted_race = _format_race(race)
            if formatted_race:
                context["race"] = formatted_race
        if rc and "rc" not in context:
            text = str(rc).replace(" ", "").upper()
            if text:
                context["rc"] = text
        if course_id and "course_id" not in context:
            cid = str(course_id).strip()
            if cid:
                context["course_id"] = cid

    meeting = context.get("meeting")
    race = context.get("race")
    if meeting and race and "rc" not in context:
        context["rc"] = f"{meeting}{race}"
    return context


def _build_leg_details(
    leg_id: str,
    *sources: Mapping[str, Any],
) -> Dict[str, Any]:
    details = {"id": leg_id}
    context = _extract_course_context(*sources)
    details.update(context)
    return details


def _extract_combo_entries(source: Any) -> List[Tuple[str, Dict[str, Any]]]:
    """Return ``(type, data)`` entries describing exotic combinations."""

    if not source:
        return []

    entries: List[Tuple[str, Dict[str, Any]]] = []
    if isinstance(source, Mapping):
        # Common container keys mapping to nested structures (``exotics`` …)
        for key in ("exotics", "combinaisons", "combos"):
            if key in source:
                entries.extend(_extract_combo_entries(source[key]))

        for combo_type, data in source.items():
            if combo_type in {"exotics", "combinaisons", "combos"}:
                continue
            if isinstance(data, Mapping):
                if not any(
                    key in data
                    for key in ("legs", "participants", "runners", "combination", "combinaison")
                ):
                    continue
                item = dict(data)
                item.setdefault("type", combo_type)
                entries.append((str(item.get("type", combo_type)).upper(), item))
            elif isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray)):
                for item in data:
                    if not isinstance(item, Mapping):
                        continue
                    if not any(
                        key in item
                        for key in ("legs", "participants", "runners", "combination", "combinaison")
                    ):
                        continue
                    obj = dict(item)
                    obj.setdefault("type", combo_type)
                    entries.append((str(obj.get("type", combo_type)).upper(), obj))
    elif isinstance(source, Sequence) and not isinstance(source, (str, bytes, bytearray)):
        for item in source:
            if not isinstance(item, Mapping):
                continue
            combo_type = (
                item.get("type")
                or item.get("bet_type")
                or item.get("kind")
                or item.get("category")
                or "CP"
            )
            if not any(
                key in item
                for key in ("legs", "participants", "runners", "combination", "combinaison")
            ):
                continue
            entries.append((str(combo_type).upper(), dict(item)))
    return entries


def _build_combo_candidates(
    combos_source: Any,
    *,
    course_context: Mapping[str, Any] | None = None,
) -> List[List[Dict[str, Any]]]:
    """Normalise combo definitions from ``combos_source`` into candidates."""

    candidates: List[List[Dict[str, Any]]] = []
    for combo_type, raw in _extract_combo_entries(combos_source):
        legs = _normalise_legs(
            raw.get("legs")
            or raw.get("participants")
            or raw.get("runners")
            or raw.get("combination")
            or raw.get("combinaison")
        )
        if not legs:
            continue
        odds = raw.get("odds") or raw.get("cote") or raw.get("expected_odds") or raw.get("payout")
        try:
            odds_val = float(odds)
        except (TypeError, ValueError):
            continue
        stake = raw.get("stake") or raw.get("mise") or raw.get("amount")
        try:
            stake_val = float(stake) if stake is not None else 1.0
        except (TypeError, ValueError):
            stake_val = 1.0
        ticket = {
            "id": raw.get("id") or raw.get("name") or "|".join(legs),
            "type": combo_type,
            "legs": legs,
            "odds": odds_val,
            "stake": stake_val,
        }
        context_sources: List[Mapping[str, Any]] = []
        if isinstance(raw, Mapping):
            context_sources.append(raw)
        if isinstance(course_context, Mapping):
            context_sources.append(course_context)
        if context_sources:
            ticket["legs_details"] = [
                _build_leg_details(leg_id, *context_sources)
                for leg_id in legs
            ]
        if "p" in raw:
            try:
                ticket["p"] = float(raw.get("p"))
            except (TypeError, ValueError):  # pragma: no cover - defensive
                pass
        candidates.append([ticket])
    return candidates


def apply_ticket_policy(
    cfg: Mapping[str, Any],
    runners: Iterable[Dict[str, Any]],
    combo_candidates: Iterable[List[Dict[str, Any]]] | None = None,
    *,
    combos_source: Any | None = None,
    ev_threshold: float | None = None,
    roi_threshold: float | None = None,
    payout_threshold: float | None = None,
    allow_heuristic: bool | None = None,
    calibration: str | os.PathLike[str] | None = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Allocate SP tickets and normalised combo templates.
    Parameters
    ----------
    cfg:
        Configuration mapping providing budget ratios and gating thresholds.
    runners:
        Iterable of runner mappings ``{"id", "name", "odds", "p"}`` used for SP
        dutching allocation.
    combo_candidates:
        Optional iterable of pre-built combination candidates. When ``None``
        the candidates are generated from ``combos_source``.
    combos_source:
        Raw exotic definitions sourced from ``partants`` JSON.
    ev_threshold, roi_threshold, payout_threshold:
        Optional overrides for validation thresholds. When ``None`` the values
        are read from ``cfg``.
    allow_heuristic:
        Deprecated toggle retained for compatibility.  Truthy values are
        ignored and combos are always evaluated with calibration data.
        calibration:
        Optional path to the payout calibration YAML forwarded to
        :func:`runner_chain.validate_exotics_with_simwrapper`

    Returns
    -------
    tuple
        ``(sp_tickets, combo_templates, info)`` where ``sp_tickets`` is the
        list of SP dutching bets, ``combo_templates`` contains validated exotic
        tickets with calibration metadata and ``info`` bubbles up notes/flags
        from the validation chain..
    """

    cfg = dict(cfg)
    runners_list = list(runners)
    budget_total = float(cfg.get("BUDGET_TOTAL", BUDGET_CAP_EUR))
    cfg.setdefault("SP_RATIO", SP_SHARE)
    cfg.setdefault("COMBO_RATIO", COMBO_SHARE)
    cfg.setdefault("MAX_TICKETS_SP", MAX_TICKETS)
    homogeneous_field = _is_homogeneous_field(runners_list)
    cfg["HOMOGENEOUS_FIELD"] = homogeneous_field

    if allow_heuristic:
        logger.warning(
            "[COMBO] allow_heuristic demandé lors de la construction des tickets; "
            "ignoré car une calibration payout versionnée est obligatoire."
        )
    allow_heuristic = False
    
    # --- SP tickets -----------------------------------------------------
    sp_tickets, _ = allocate_dutching_sp(cfg, runners_list)
    sp_tickets.sort(key=lambda t: t.get("ev_ticket", 0.0), reverse=True)
    max_tickets = int(cfg.get("MAX_TICKETS_SP", len(sp_tickets)))
    sp_tickets = sp_tickets[:max_tickets]

    # --- Combo templates ------------------------------------------------
    info: Dict[str, Any] = {"notes": [], "flags": {}}
    if bool(cfg.get("PAUSE_EXOTIQUES")):
        return sp_tickets, [], info

    if combo_candidates is None:
        base_context = combos_source if isinstance(combos_source, Mapping) else None
        combo_candidates = _build_combo_candidates(
            combos_source,
            course_context=base_context,
        )
    else:
        combo_candidates = list(combo_candidates)
    if homogeneous_field and combo_candidates:
        filtered_candidates: List[List[Dict[str, Any]]] = []
        for candidate in combo_candidates:
            if not candidate:
                continue
            combo_type = str(candidate[0].get("type", "")).upper()
            if combo_type in {"TRIO", "ZE4", "ZE4+", "ZE4X"}:
                continue
            filtered_candidates.append(candidate)
        combo_candidates = filtered_candidates
        if not combo_candidates:
            info.setdefault("notes", []).append("homogeneous_field_filtered")
    if not combo_candidates:
        return sp_tickets, [], info

    combo_budget = budget_total * float(cfg.get("COMBO_RATIO", COMBO_SHARE))
    ev_threshold = float(cfg.get("EV_MIN_GLOBAL", EV_MIN_COMBO)) if ev_threshold is None else ev_threshold
    roi_threshold = float(cfg.get("ROI_MIN_GLOBAL", 0.0)) if roi_threshold is None else roi_threshold
    payout_threshold = (
        float(cfg.get("MIN_PAYOUT_COMBOS", PAYOUT_MIN_COMBO))
        if payout_threshold is None
        else payout_threshold
    )
    sharpe_threshold = float(cfg.get("SHARPE_MIN", 0.0))

    calib_candidate = (
        calibration
        or os.environ.get("GPI_PAYOUT_CALIBRATION", "config/payout_calibration.yaml")
    )
    try:
        ok_calib = (
            bool(calib_candidate)
            and os.path.exists(calib_candidate)
            and os.path.getsize(calib_candidate) > 0
        )
    except Exception:
        ok_calib = False

    if not ok_calib:
        notes = info.setdefault("notes", [])
        if "calibration_missing" not in notes:
            notes.append("calibration_missing")
        if "no_calibration_yaml → exotiques désactivés" not in notes:
            notes.append("no_calibration_yaml → exotiques désactivés")
        return sp_tickets, [], info
        
    validated, info = validate_exotics_with_simwrapper(
        combo_candidates,
        bankroll=combo_budget,
        ev_min=ev_threshold,
        roi_min=roi_threshold,
        payout_min=payout_threshold,
        sharpe_min=sharpe_threshold,
        allow_heuristic=allow_heuristic,
        calibration=calibration,
    )

    if not validated:
        return sp_tickets, [], info

    # Build a lookup to merge calibration metadata back into validated tickets.
    lookup: Dict[Tuple[str, Tuple[str, ...]], Dict[str, Any]] = {}
    for candidate in combo_candidates:
        if not candidate:
            continue
        base = dict(candidate[0])
        leg_details = base.get("legs_details")
        if isinstance(leg_details, list):
            base["legs_details"] = [
                dict(ld) if isinstance(ld, Mapping) else {"id": str(ld)}
                for ld in leg_details
            ]
            base_legs = [_leg_lookup_key(ld) for ld in base["legs_details"]]
        else:
            base_legs = [_leg_lookup_key(leg) for leg in base.get("legs", [])]
            if base_legs:
                base["legs_details"] = [
                    {"id": leg_id} for leg_id in base_legs
                ]
        base["legs"] = list(base_legs)
        key = (
            str(base.get("type", "CP")),
            tuple(sorted(base_legs)),
        )
        lookup[key] = base

    combo_tickets: List[Dict[str, Any]] = []
    for ticket in validated:
        key = (
            str(ticket.get("type", "CP")),
            tuple(sorted(str(leg) for leg in ticket.get("legs", []))),
        )
        base = lookup.get(key)
        if base is None:
            continue
        merged = dict(base)
        if isinstance(base.get("legs_details"), list):
            merged["legs_details"] = [dict(ld) for ld in base["legs_details"]]
        merged.update({k: v for k, v in ticket.items() if k not in {"legs"}})
        if isinstance(ticket.get("legs_details"), list):
            merged["legs_details"] = [
                dict(ld) if isinstance(ld, Mapping) else {"id": _leg_lookup_key(ld)}
                for ld in ticket.get("legs_details", [])
            ]
        merged["id"] = ticket.get("id", merged.get("id"))
        merged["type"] = ticket.get("type", merged.get("type"))
        if isinstance(merged.get("legs_details"), list) and merged["legs_details"]:
            merged["legs"] = [_leg_lookup_key(ld) for ld in merged["legs_details"]]
        else:
            merged["legs"] = [
                _leg_lookup_key(leg)
                for leg in ticket.get("legs", merged.get("legs", []))
            ]
        merged["ev_check"] = ticket.get("ev_check", {})
        if "flags" in ticket:
            merged["flags"] = list(ticket.get("flags", []))
        combo_tickets.append(merged)


    return sp_tickets, combo_tickets, info

# Provide a convenient alias
build_tickets = apply_ticket_policy


__all__ = [
    "allow_combo",
    "apply_ticket_policy",
    "build_tickets",
    "BUDGET_CAP_EUR",
    "SP_SHARE",
    "COMBO_SHARE",
    "EV_MIN_COMBO",
    "PAYOUT_MIN_COMBO",
    "MAX_TICKETS",
]
