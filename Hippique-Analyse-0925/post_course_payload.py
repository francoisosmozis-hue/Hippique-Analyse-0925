"""Shared helpers for post-course payload generation and reporting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Sequence

JsonDict = dict[str, Any]

POST_COURSE_SCHEMA_VERSION = "1.0"
CSV_HEADER = (
    "R/C;hippodrome;date;discipline;mises;ROI_reel;result_moyen;"
    "ROI_reel_moyen;Brier_total;Brier_moyen;EV_total;EV_ecart;model"
)


@dataclass
class PostCourseSummary:
    """Aggregate metrics computed after enriching the tickets."""

    total_gain: float
    total_stake: float
    roi: float
    ev_total: float
    ev_diff_total: float
    result_mean: float
    roi_ticket_mean: float
    brier_total: float
    brier_mean: float

    def as_dict(self) -> JsonDict:
        return {
            "total_gain": self.total_gain,
            "total_stake": self.total_stake,
            "roi": self.roi,
            "ev_total": self.ev_total,
            "ev_diff_total": self.ev_diff_total,
            "result_mean": self.result_mean,
            "roi_ticket_mean": self.roi_ticket_mean,
            "brier_total": self.brier_total,
            "brier_mean": self.brier_mean,
        }


def merge_meta(arrivee: JsonDict | None, tickets: JsonDict | None) -> JsonDict:
    """Merge metadata from ``arrivee`` and ``tickets`` payloads."""

    meta: JsonDict = {}

    if isinstance(tickets, dict):
        tickets_meta = tickets.get("meta")
        if isinstance(tickets_meta, dict):
            meta.update(tickets_meta)

    if isinstance(arrivee, dict):
        arrivee_meta = arrivee.get("meta")
        if isinstance(arrivee_meta, dict):
            for key, value in arrivee_meta.items():
                meta.setdefault(key, value)

    for key in ("rc", "hippodrome", "date", "discipline", "model", "MODEL"):
        if meta.get(key):
            continue
        source_value: Any | None = None
        if isinstance(arrivee, dict):
            source_value = arrivee.get(key)
            if source_value is None:
                arrivee_meta = arrivee.get("meta") if isinstance(arrivee, dict) else None
                if isinstance(arrivee_meta, dict):
                    source_value = arrivee_meta.get(key)
        if source_value is None and isinstance(tickets, dict):
            source_value = tickets.get(key)
        if source_value is not None:
            meta[key] = source_value

    if "model" not in meta and "MODEL" in meta:
        meta["model"] = meta["MODEL"]

    return meta


def _iter_tickets(tickets: Iterable[JsonDict | Any]) -> Iterator[JsonDict]:
    for ticket in tickets:
        if isinstance(ticket, dict):
            yield ticket


def compute_post_course_summary(
    tickets: Iterable[JsonDict], winners: Sequence[str] | Iterable[str]
) -> PostCourseSummary:
    """Update ``tickets`` with realised metrics and return aggregates."""

    winner_set = {str(w) for w in winners}

    total_stake = 0.0
    total_gain = 0.0
    total_ev = 0.0
    total_diff_ev = 0.0
    total_result = 0.0
    total_roi_ticket = 0.0
    total_brier = 0.0
    count = 0

    for ticket in _iter_tickets(tickets):
        stake = float(ticket.get("stake", 0.0) or 0.0)
        odds = float(ticket.get("odds", 0.0) or 0.0)
        ticket_id = ticket.get("id")
        is_winner = str(ticket_id) in winner_set if ticket_id is not None else False
        gain = stake * odds if is_winner else 0.0
        ticket["gain_reel"] = round(gain, 2)
        result_value = 1 if gain else 0
        ticket["result"] = result_value
        roi_ticket = (gain - stake) / stake if stake else 0.0
        ticket["roi_reel"] = round(roi_ticket, 4)

        total_stake += stake
        total_gain += gain
        total_result += result_value
        total_roi_ticket += roi_ticket
        count += 1

        ev_value: float | None = None
        if "ev" in ticket:
            try:
                ev_value = float(ticket.get("ev", 0.0) or 0.0)
            except (TypeError, ValueError):
                ev_value = 0.0
        elif "p" in ticket:
            prob = float(ticket.get("p", 0.0) or 0.0)
            ev_value = stake * (prob * (odds - 1) - (1 - prob))
        if ev_value is not None:
            diff_ev = gain - ev_value
            ticket["ev_ecart"] = round(diff_ev, 2)
            total_ev += ev_value
            total_diff_ev += diff_ev

        if "p" in ticket:
            prob = float(ticket.get("p", 0.0) or 0.0)
            brier = (result_value - prob) ** 2
            ticket["brier"] = round(brier, 4)
            total_brier += brier

    roi = (total_gain - total_stake) / total_stake if total_stake else 0.0
    result_mean = total_result / count if count else 0.0
    roi_ticket_mean = total_roi_ticket / count if count else 0.0
    brier_mean = total_brier / count if count else 0.0

    return PostCourseSummary(
        total_gain=total_gain,
        total_stake=total_stake,
        roi=roi,
        ev_total=total_ev,
        ev_diff_total=total_diff_ev,
        result_mean=result_mean,
        roi_ticket_mean=roi_ticket_mean,
        brier_total=total_brier,
        brier_mean=brier_mean,
    )


def summarise_ticket_metrics(tickets: Iterable[JsonDict]) -> PostCourseSummary:
    """Return aggregate metrics from tickets enriched with realised fields."""

    total_stake = 0.0
    total_gain = 0.0
    total_ev = 0.0
    total_diff_ev = 0.0
    total_result = 0.0
    total_roi_ticket = 0.0
    total_brier = 0.0
    count = 0

    for ticket in _iter_tickets(tickets):
        stake = float(ticket.get("stake", 0.0) or 0.0)
        odds = float(ticket.get("odds", 0.0) or 0.0)
        gain = float(ticket.get("gain_reel", 0.0) or 0.0)
        roi_ticket = float(ticket.get("roi_reel", 0.0) or 0.0)
        result_value = ticket.get("result")
        if result_value is None:
            result_value = 1 if gain else 0
        result_float = float(result_value)

        total_stake += stake
        total_gain += gain
        total_result += result_float
        total_roi_ticket += roi_ticket
        count += 1

        prob = float(ticket.get("p", 0.0) or 0.0)
        total_ev += stake * (prob * odds - 1.0)
        total_diff_ev += gain - stake

        brier = ticket.get("brier")
        if brier is None and "p" in ticket:
            brier = (result_float - prob) ** 2
        total_brier += float(brier or 0.0)

    roi = (total_gain - total_stake) / total_stake if total_stake else 0.0
    result_mean = total_result / count if count else 0.0
    roi_ticket_mean = total_roi_ticket / count if count else 0.0
    brier_mean = total_brier / count if count else 0.0

    return PostCourseSummary(
        total_gain=total_gain,
        total_stake=total_stake,
        roi=roi,
        ev_total=total_ev,
        ev_diff_total=total_diff_ev,
        result_mean=result_mean,
        roi_ticket_mean=roi_ticket_mean,
        brier_total=total_brier,
        brier_mean=brier_mean,
    )


def apply_summary_to_ticket_container(container: JsonDict, summary: PostCourseSummary) -> None:
    """Update ``container`` in place with aggregate metrics from ``summary``."""

    container["roi_reel"] = summary.roi
    container["result_moyen"] = summary.result_mean
    container["roi_reel_moyen"] = summary.roi_ticket_mean
    container["brier_total"] = summary.brier_total
    container["brier_moyen"] = summary.brier_mean
    container["ev_total"] = summary.ev_total
    container["ev_ecart_total"] = summary.ev_diff_total


def build_payload(
    *,
    meta: JsonDict,
    arrivee: JsonDict | None,
    tickets: Iterable[JsonDict],
    summary: PostCourseSummary,
    winners: Sequence[str] | Iterable[str] | None = None,
    ev_estimees: JsonDict | None = None,
    places: int | None = None,
) -> JsonDict:
    """Construct the normalised post-course payload."""

    tickets_list = [dict(t) for t in _iter_tickets(tickets)]
    winners_list = [str(w) for w in winners] if winners is not None else []

    arrivee_section: JsonDict = {}
    if isinstance(arrivee, dict):
        arrivee_section.update(arrivee)
    arrivee_section.setdefault("rc", meta.get("rc"))
    arrivee_section.setdefault("date", meta.get("date"))
    if winners_list:
        arrivee_section["result"] = winners_list
    if places is not None:
        arrivee_section["places"] = places

    observed = {
        "roi_reel": summary.roi,
        "result_moyen": summary.result_mean,
        "roi_reel_moyen": summary.roi_ticket_mean,
        "brier_total": summary.brier_total,
        "brier_moyen": summary.brier_mean,
        "ev_total": summary.ev_total,
        "ev_ecart_total": summary.ev_diff_total,
    }

    payload: JsonDict = {
        "schema_version": POST_COURSE_SCHEMA_VERSION,
        "meta": meta,
        "arrivee": arrivee_section,
        "tickets": tickets_list,
        "mises": {
            "total": round(summary.total_stake, 2),
            "gains": round(summary.total_gain, 2),
        },
        "ev_estimees": ev_estimees or {},
        "ev_observees": observed,
    }

    return payload


def build_payload_from_sources(
    arrivee: JsonDict | None,
    tickets_container: JsonDict | None,
    *,
    places: int | None = None,
) -> JsonDict:
    """Helper to produce a payload when metrics are already present."""

    meta = merge_meta(arrivee or {}, tickets_container or {})
    tickets_list = []
    ev_estimees: JsonDict | None = None
    if isinstance(tickets_container, dict):
        maybe_tickets = tickets_container.get("tickets")
        if isinstance(maybe_tickets, list):
            tickets_list = [dict(t) for t in _iter_tickets(maybe_tickets)]
        ev_candidate = tickets_container.get("ev")
        if isinstance(ev_candidate, dict):
            ev_estimees = ev_candidate
    summary = summarise_ticket_metrics(tickets_list)
    winners = []
    if isinstance(arrivee, dict):
        result = arrivee.get("result")
        if isinstance(result, Sequence):
            winners = [str(x) for x in result]
    return build_payload(
        meta=meta,
        arrivee=arrivee,
        tickets=tickets_list,
        summary=summary,
        winners=winners,
        ev_estimees=ev_estimees,
        places=places,
    )


def format_csv_line(meta: JsonDict, summary: PostCourseSummary) -> str:
    """Return the CSV summary line associated with ``summary``."""

    return (
        f'{meta.get("rc", "")};{meta.get("hippodrome", "")};{meta.get("date", "")};'
        f'{meta.get("discipline", "")};{summary.total_stake:.2f};{summary.roi:.4f};'
        f'{summary.result_mean:.4f};{summary.roi_ticket_mean:.4f};'
        f'{summary.brier_total:.4f};{summary.brier_mean:.4f};'
        f'{summary.ev_total:.2f};{summary.ev_diff_total:.2f};'
        f'{meta.get("model", meta.get("MODEL", ""))}'
    )
