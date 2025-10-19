#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Dict

try:  # pragma: no cover - optional dependency
    import yaml
except Exception:  # pragma: no cover - yaml is optional for the CLI
    yaml = None  # type: ignore[assignment]


class ValidationError(Exception):
    """Raised when EV metrics do not meet required thresholds."""


_LOG = logging.getLogger(__name__)
_MISSING = object()


def _log_ev_metrics(
    p_success: float | None,
    payout_expected: float | None,
    stake: float | None,
    ev_ratio: float | None,
) -> None:
    """Log the EV context associated with a validation run.

    Parameters
    ----------
    p_success, payout_expected, stake, ev_ratio:
        Contextual metrics associated with the EV computation.  ``None`` values
        are logged verbatim so that missing data can be inspected downstream.
    """

    payload = {
        "p_success": p_success,
        "payout_expected": payout_expected,
        "stake": stake,
        "EV_ratio": ev_ratio,
    }
    _LOG.info("[validate_ev] context %s", payload)


def summarise_validation(*validators: Callable[[], object]) -> dict[str, bool | str]:
    """Run validators and return a structured summary of the outcome.

    Parameters
    ----------
    validators:
        Callables executing validation logic. They should raise an exception
        when the validation fails and return a truthy value otherwise.

    Returns
    -------
    dict
        A dictionary with two keys:
        ``ok`` (bool) indicating whether all validators passed and
        ``reason`` (str) containing the first failure message or ``""``.
    """

    for check in validators:
        try:
            check()
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}
    return {"ok": True, "reason": ""}


def must_have(value, msg):
    """Raise ``RuntimeError`` if ``value`` is falsy."""
    if not value:
        raise RuntimeError(msg)
    return value


def validate_inputs(cfg, partants, odds, stats_je):
    """Validate raw inputs before any EV computation.

    This simplified validator only checks a single odds snapshot.

    Parameters
    ----------
    cfg : dict
        Configuration containing flags such as ``ALLOW_JE_NA``.
    partants : list[dict]
        List of runners with at least an ``id`` key.
    odds : dict
        Mapping ``id`` -> cote for the snapshot to analyse.
    stats_je : dict
        Dictionary containing at least a ``coverage`` percentage.
    """

    allow_je_na = cfg.get("ALLOW_JE_NA", False)
    if not partants or len(partants) < 6:
        raise ValidationError("Nombre de partants insuffisant (min 6)")

    if not odds:
        raise ValidationError("Cotes manquantes")
    for cid, cote in odds.items():
        if cote is None:
            raise ValidationError(f"Cote manquante pour {cid}")

    if not allow_je_na:
        coverage = stats_je.get("coverage") if stats_je else None
        if coverage is None or float(coverage) < 80:
            raise ValidationError("Couverture J/E insuffisante (<80%)")

    return True


def validate(h30: dict, h5: dict, allow_je_na: bool) -> bool:
    ids30 = [x["id"] for x in h30.get("runners", [])]
    ids05 = [x["id"] for x in h5.get("runners", [])]
    if set(ids30) != set(ids05):
        raise ValueError("Partants incohérents (H-30 vs H-5).")
    if not ids05:
        raise ValueError("Aucun partant.")

    for snap, label in [(h30, "H-30"), (h5, "H-5")]:
        for r in snap.get("runners", []):
            if "odds" not in r or r["odds"] in (None, ""):
                raise ValueError(
                    f"Cotes manquantes {label} pour {r.get('name', r.get('id'))}."
                )
            try:
                if float(r["odds"]) <= 1.01:
                    raise ValueError(
                        f"Cote invalide {label} pour {r.get('name', r.get('id'))}: {r['odds']}"
                    )
            except Exception:
                raise ValueError(
                    f"Cote non numérique {label} pour {r.get('name', r.get('id'))}: {r.get('odds')}"
                )
    if not allow_je_na:
        for r in h5.get("runners", []):
            je = r.get("je_stats", {})
            if not je or ("j_win" not in je and "e_win" not in je):
                raise ValueError(f"Stats J/E manquantes: {r.get('name', r.get('id'))}")
    return True


def validate_ev(
    ev_sp: float,
    ev_global: float | None,
    need_combo: bool = True,
    *,
    p_success: float | None = _MISSING,
    payout_expected: float | None = _MISSING,
    stake: float | None = _MISSING,
    ev_ratio: float | None = _MISSING,
) -> bool | dict[str, str]:
    """Validate SP and combined EVs against environment thresholds.

    Parameters
    ----------
    ev_sp:
        Expected value for simple bets.
    ev_global:
        Expected value for combined bets. Ignored when ``need_combo`` is
        ``False``.
    need_combo:
        When ``True`` both SP and combined EVs must satisfy their respective
        thresholds.

    Other Parameters
    ----------------
    p_success, payout_expected, stake, ev_ratio:
        Optional contextual metrics associated with the EV computation. When
        provided they are logged and validated for completeness.

    Returns
    -------
    bool or dict
        ``True`` if all required thresholds are met.  When contextual metrics
        are provided but missing the function returns a payload describing the
        ``invalid_input`` status instead of raising an exception.

    Raises
    ------
    ValidationError
        If any required EV is below its threshold.
    """

    metrics_supplied = any(
        value is not _MISSING for value in (p_success, payout_expected, stake, ev_ratio)
    )
    _log_ev_metrics(
        None if p_success is _MISSING else p_success,
        None if payout_expected is _MISSING else payout_expected,
        None if stake is _MISSING else stake,
        None if ev_ratio is _MISSING else ev_ratio,
    )

    if metrics_supplied:
        if p_success in (_MISSING, None):
            return {
                "status": "invalid_input",
                "reason": "missing p_success",
            }
        if payout_expected in (_MISSING, None):
            return {
                "status": "invalid_input",
                "reason": "missing payout_expected",
            }

    min_sp = float(os.getenv("EV_MIN_SP", 0.15))
    min_global = float(os.getenv("EV_MIN_GLOBAL", 0.35))

    if ev_sp < min_sp:
        raise ValidationError("EV SP below threshold")

    if need_combo:
        if ev_global is None or ev_global < min_global:
            raise ValidationError("EV global below threshold")

    return True


def validate_policy(
    ev_global: float, roi_global: float, min_ev: float, min_roi: float
) -> bool:
    """Validate global EV and ROI against minimum thresholds."""
    if ev_global < min_ev:
        raise ValidationError("EV global below threshold")
    if roi_global < min_roi:
        raise ValidationError("ROI global below threshold")
    return True


def validate_budget(
    stakes: Dict[str, float], budget_cap: float, max_vol_per_horse: float
) -> bool:
    """Ensure total stake and per-horse stakes respect budget constraints."""
    total = sum(stakes.values())
    if total > budget_cap:
        raise ValidationError("Budget cap exceeded")
    per_horse_cap = budget_cap * max_vol_per_horse
    for horse, stake in stakes.items():
        if stake > per_horse_cap:
            raise ValidationError(f"Stake cap exceeded for {horse}")
    return True


def validate_combos(expected_payout: float, min_payout: float = 12.0) -> bool:
    """Validate that combined expected payout exceeds the minimum required.

    Parameters
    ----------
    expected_payout:
        Expected payout from the combined tickets.
    min_payout:
        Minimum acceptable payout. Defaults to ``12.0`` (euros).
    """
    if expected_payout <= min_payout:
        raise ValidationError("expected payout for combined bets below threshold")
    return True


def combos_allowed(
    ev_basket: float,
    expected_payout: float,
    *,
    min_ev: float = 0.40,
    min_payout: float = 12.0,
) -> bool:
    """Return ``True`` when combinés satisfy EV and payout guardrails."""

    try:
        ev_value = float(ev_basket)
    except (TypeError, ValueError):
        ev_value = 0.0
    try:
        payout_value = float(expected_payout)
    except (TypeError, ValueError):
        payout_value = 0.0

    if ev_value < min_ev:
        return False
    if payout_value < min_payout:
        return False
    return True


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


_PARTANTS_CANDIDATES = (
    "partants.json",
    "partants_h5.json",
    "partants_H5.json",
)

_STATS_CANDIDATES = (
    "stats_je.json",
    "je_stats.json",
    "stats.json",
)

_ODDS_CANDIDATES = {
    "H5": (
        "odds_h5.json",
        "h5.json",
        "snapshot_H5.json",
        "snapshot_H-5.json",
    ),
    "H30": (
        "odds_h30.json",
        "h30.json",
        "snapshot_H30.json",
        "snapshot_H-30.json",
    ),
}

_CONFIG_CANDIDATES = (
    "gpi.yml",
    "gpi.yaml",
    "config.yml",
    "config.yaml",
)


def _normalise_phase(phase: str | None) -> str:
    if not phase:
        return "H5"
    cleaned = phase.strip().upper().replace("-", "")
    if cleaned not in {"H5", "H30"}:
        raise ValueError(f"Phase inconnue: {phase!r} (attendu H5 ou H30)")
    return "H5" if cleaned == "H5" else "H30"


def _load_json_payload(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_first_existing(directory: Path, candidates: tuple[str, ...]) -> Path | None:
    for name in candidates:
        candidate = directory / name
        if candidate.exists():
            return candidate
    return None


def _load_partants(path: Path) -> list[dict]:
    payload = _load_json_payload(path)
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        runners = payload.get("runners")
        if isinstance(runners, list):
            return [p for p in runners if isinstance(p, dict)]
    raise ValueError(f"Format partants invalide dans {path}")


def _odds_from_runner(runner: dict) -> tuple[str | None, float | None]:
    cid = runner.get("id") or runner.get("ID") or runner.get("runner_id")
    num = runner.get("num") or runner.get("number") or runner.get("programmeNumber")
    odds = runner.get("odds") or runner.get("cote") or runner.get("rapport")
    if isinstance(odds, str):
        odds = odds.replace(",", ".")
    try:
        val = float(odds) if odds is not None else None
    except (TypeError, ValueError):
        val = None
    identifier: str | None = None
    if cid is not None:
        identifier = str(cid)
    elif num is not None:
        identifier = str(num)
    return identifier, val


def _load_odds(path: Path) -> dict[str, float]:
    payload = _load_json_payload(path)
    odds_map: dict[str, float] = {}
    if isinstance(payload, dict):
        runners = (
            payload.get("runners") if isinstance(payload.get("runners"), list) else None
        )
        if runners is not None:
            for runner in runners:
                if not isinstance(runner, dict):
                    continue
                identifier, value = _odds_from_runner(runner)
                if identifier is None or value is None:
                    continue
                odds_map[str(identifier)] = float(value)
        else:
            for key, value in payload.items():
                try:
                    odds_map[str(key)] = float(value)
                except (TypeError, ValueError):
                    continue
    elif isinstance(payload, list):
        for runner in payload:
            if not isinstance(runner, dict):
                continue
            identifier, value = _odds_from_runner(runner)
            if identifier is None or value is None:
                continue
            odds_map[str(identifier)] = float(value)

    if not odds_map:
        raise ValueError(f"Impossible d'extraire les cotes depuis {path}")
    return odds_map


def _load_stats(path: Path) -> dict:
    payload = _load_json_payload(path)
    if isinstance(payload, dict):
        return payload
    raise ValueError(f"Format stats invalide dans {path}")


def _load_config(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    if path.suffix.lower() in {".yml", ".yaml"} and yaml is not None:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data or {}
    if path.suffix.lower() in {".json"}:
        payload = _load_json_payload(path)
        if isinstance(payload, dict):
            return payload
    return {}


def _resolve_rc_directory(
    artefacts_dir: str | None,
    base_dir: str | None,
    reunion: str | None,
    course: str | None,
) -> Path:
    if artefacts_dir:
        return Path(artefacts_dir)
    if reunion and course:
        root = Path(base_dir) if base_dir else Path("data")
        return root / f"{reunion}{course}"
    raise ValueError(
        "Impossible de déterminer le dossier artefacts (fournir --artefacts ou --reunion/--course)"
    )


def _discover_file(
    rc_dir: Path, candidates: tuple[str, ...], *, required: bool = True
) -> Path | None:
    path = _find_first_existing(rc_dir, candidates)
    if path is None and required:
        names = ", ".join(candidates)
        raise FileNotFoundError(f"Aucun fichier trouvé dans {rc_dir} parmi: {names}")
    return path


def _prepare_validation_inputs(
    args: argparse.Namespace,
) -> tuple[dict, list[dict], dict[str, float], dict]:
    phase = _normalise_phase(args.phase)
    rc_dir = _resolve_rc_directory(
        args.artefacts, args.base_dir, args.reunion, args.course
    )

    partants_path = (
        Path(args.partants)
        if args.partants
        else _discover_file(rc_dir, _PARTANTS_CANDIDATES)
    )
    stats_path = (
        Path(args.stats_je)
        if args.stats_je
        else _discover_file(rc_dir, _STATS_CANDIDATES, required=False)
    )
    odds_candidates = _ODDS_CANDIDATES.get(phase, _ODDS_CANDIDATES["H5"])
    odds_path = (
        Path(args.odds) if args.odds else _discover_file(rc_dir, odds_candidates)
    )
    config_path: Path | None
    if args.config:
        config_path = Path(args.config)
    else:
        config_path = _discover_file(rc_dir, _CONFIG_CANDIDATES, required=False)

    cfg = _load_config(config_path)
    if args.allow_je_na:
        cfg = dict(cfg)
        cfg["ALLOW_JE_NA"] = True

    partants = _load_partants(partants_path)
    odds = _load_odds(odds_path)
    stats = _load_stats(stats_path) if stats_path else {}
    return cfg, partants, odds, stats


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Valide les artefacts d'une course via validate_inputs.",
    )
    parser.add_argument("--artefacts", help="Dossier contenant les artefacts de course")
    parser.add_argument(
        "--base-dir", help="Dossier racine où trouver R?C?", default=None
    )
    parser.add_argument("--reunion", help="Identifiant réunion (ex: R1)")
    parser.add_argument("--course", help="Identifiant course (ex: C3)")
    parser.add_argument("--phase", help="Phase (H5 ou H30)", default="H5")
    parser.add_argument("--partants", help="Chemin explicite vers partants.json")
    parser.add_argument("--odds", help="Chemin explicite vers les cotes")
    parser.add_argument("--stats-je", help="Chemin explicite vers stats_je.json")
    parser.add_argument("--config", help="Chemin configuration GPI (YAML/JSON)")
    parser.add_argument(
        "--allow-je-na",
        action="store_true",
        help="Force ALLOW_JE_NA dans la configuration",
    )

    try:
        cfg, partants, odds, stats = _prepare_validation_inputs(parser.parse_args(argv))
    except FileNotFoundError as exc:
        parser.error(str(exc))
    except ValueError as exc:
        parser.error(str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        parser.error(f"Erreur inattendue: {exc}")

    summary = summarise_validation(partial(validate_inputs, cfg, partants, odds, stats))
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    return _cli(argv)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())