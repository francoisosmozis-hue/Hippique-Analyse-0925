"""Module pour les règles métier et les filtres.

Contient les règles de validation spécifiques au projet, comme le filtrage
des tickets basé sur les cotes.
"""

from collections.abc import Iterable
from typing import Any

# --- RÈGLES ANTI-COTES FAIBLES (SP min 4/1 ; CP somme > 6.0 déc) ---------------
MIN_SP_DEC_ODDS = 5.0  # 4/1 = 5.0
MIN_CP_SUM_DEC = 6.0  # (o1-1)+(o2-1) ≥ 4  <=> (o1+o2) ≥ 6.0

def _norm_float(value: Any) -> float | None:
    """Convertit une valeur en float, gérant les virgules décimales."""
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return None

def filter_tickets_by_odds(payload: dict[str, Any]) -> None:
    """Filtre les tickets SP et CP d'un payload en fonction de leurs cotes.

    La fonction modifie le payload en place.
    - SP: Garde les tickets si au moins une cote est >= MIN_SP_DEC_ODDS.
    - CP: Garde les tickets si la somme des cotes est >= MIN_CP_SUM_DEC.
    """
    if not isinstance(payload.get("tickets"), list):
        return

    tickets = payload.get("tickets", [])
    kept: list[dict[str, Any]] = []

    def _append_note(message: str) -> None:
        notes = payload.get("notes")
        if isinstance(notes, list):
            notes.append(message)
        else:
            payload["notes"] = [message]

    for ticket in tickets:
        if not isinstance(ticket, dict):
            kept.append(ticket)
            continue

        typ = str(ticket.get("type") or "").upper()
        lab = str(ticket.get("label") or "").upper()

        # 1) SP (toutes variantes de dutching place)
        if lab == "SP_DUTCHING_GPIv51" or typ in (
            "SP",
            "SIMPLE_PLACE_DUTCHING",
            "DUTCHING_SP",
            "PLACE_DUTCHING",
        ):
            legs = ticket.get("legs") or ticket.get("bets") or []
            if not isinstance(legs, list):
                if isinstance(legs, Iterable) and not isinstance(legs, (str, bytes)):
                    legs = list(legs)
                else:
                    legs = []

            new_legs = []
            for leg in legs:
                if not isinstance(leg, dict):
                    continue
                odds = None
                for key in ("cote_place", "odds", "cote", "odd"):
                    if leg.get(key) is not None:
                        odds = _norm_float(leg.get(key))
                        break
                if odds is None:
                    market = payload.get("market") or {}
                    horses = market.get("horses") if isinstance(market, dict) else []
                    num = str(leg.get("num") or leg.get("horse") or "")
                    mh = None
                    if isinstance(horses, list):
                        mh = next(
                            (h for h in horses if isinstance(h, dict) and str(h.get("num")) == num),
                            None,
                        )
                    if mh and mh.get("cote") is not None:
                        odds = _norm_float(mh.get("cote"))
                if odds is not None and odds >= MIN_SP_DEC_ODDS:
                    new_legs.append(leg)

            if new_legs:
                ticket_filtered = dict(ticket)
                ticket_filtered["legs"] = new_legs
                kept.append(ticket_filtered)
            else:
                _append_note("SP retiré: toutes les cotes < 4/1 (5.0 déc).")
            continue

        # 2) COUPLÉ PLACÉ (ou libellés équivalents)
        if typ in ("COUPLE", "COUPLE_PLACE", "CP", "COUPLÉ PLACÉ", "COUPLE PLACÉ"):
            legs_raw = ticket.get("legs") or []
            legs = [leg for leg in legs_raw if isinstance(leg, dict)]
            if len(legs) != 2:
                kept.append(ticket)
                _append_note("Avertissement: CP non-binaire (≠2 jambes).")
                continue
            odds_list: list[float | None] = []
            for leg in legs:
                odds = None
                for key in ("cote_place", "odds", "cote", "odd"):
                    if leg.get(key) is not None:
                        odds = _norm_float(leg.get(key))
                        break
                if odds is None:
                    market = payload.get("market") or {}
                    horses = market.get("horses") if isinstance(market, dict) else []
                    num = str(leg.get("num") or leg.get("horse") or "")
                    mh = None
                    if isinstance(horses, list):
                        mh = next(
                            (h for h in horses if isinstance(h, dict) and str(h.get("num")) == num),
                            None,
                        )
                    if mh and mh.get("cote") is not None:
                        odds = _norm_float(mh.get("cote"))
                odds_list.append(odds)
            if all(o is not None for o in odds_list):
                assert len(odds_list) == 2  # for type checkers
                if (odds_list[0] + odds_list[1]) >= MIN_CP_SUM_DEC:
                    kept.append(ticket)
                else:
                    _append_note(
                        f"CP retiré: somme des cotes décimales {odds_list[0]:.2f}+{odds_list[1]:.2f} < 6.00 (règle ≥ 4/1 cumulés)."
                    )
            else:
                _append_note("CP retiré: cotes manquantes (règle >4/1 non vérifiable).")
            continue

        kept.append(ticket)

    payload["tickets"] = kept
