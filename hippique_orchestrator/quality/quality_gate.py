# hippique_orchestrator/quality/quality_gate.py
"""
Contains the logic for assessing the quality of the collected data for a race.
"""
from typing import List, Dict, Tuple, Optional

from hippique_orchestrator.contracts.models import Race, Runner, OddsSnapshot, DataQualityReport

DEFAULT_THRESHOLD = 70

def compute_quality(
    race: Race, 
    runners: List[Runner], 
    snapshots_by_phase: Dict[str, OddsSnapshot],
    extra_fields: Optional[Dict] = None
) -> DataQualityReport:
    """
    Computes a quality score and generates a report based on available data.
    """
    score = 0
    reasons = []
    missing_fields = []
    
    # --- Scoring Logic ---

    # Rule: Odds presence
    if 'H30' in snapshots_by_phase and snapshots_by_phase['H30'].odds_place:
        score += 25
        reasons.append("h30_odds_present")
    else:
        missing_fields.append("odds.H30")

    if 'H5' in snapshots_by_phase and snapshots_by_phase['H5'].odds_place:
        score += 25
        reasons.append("h5_odds_present")
    else:
        missing_fields.append("odds.H5")

    # Rule: Drift calculable
    if 'H30' in snapshots_by_phase and 'H5' in snapshots_by_phase:
        score += 15
        reasons.append("drift_calculable")
    else:
        reasons.append("drift_not_calculable")
    
    # Rule: Chronos presence
    if runners:
        runners_with_chrono = sum(1 for r in runners if r.chrono_recent)
        if (runners_with_chrono / len(runners)) >= 0.5:
            score += 20
            reasons.append("chrono_coverage_sufficient")
        else:
            missing_fields.append("runners.chrono_recent")

    # Rule: Jockey/trainer stats
    if runners:
        runners_with_stats = sum(1 for r in runners if r.driver_jockey and r.trainer)
        if (runners_with_stats / len(runners)) >= 0.5:
            score += 15
            reasons.append("stats_coverage_sufficient")
        else:
            missing_fields.append("runners.driver_jockey")
            missing_fields.append("runners.trainer")

    # Rule: Runner count coherence (simplified)
    # A real implementation would compare runner sets between phases.
    if race.runners_count == len(runners):
        score += 15
        reasons.append("runner_count_coherent")
    else:
        reasons.append(f"runner_count_mismatch (expected {race.runners_count}, got {len(runners)})")

    # --- Penalties ---
    for phase, snapshot in snapshots_by_phase.items():
        if snapshot.overround_place and not (0.8 < snapshot.overround_place < 1.5):
            score -= 20
            reasons.append(f"overround_aberrant_in_{phase}")

    return DataQualityReport(
        score=max(0, min(100, score)),
        reasons=reasons,
        missing_fields=missing_fields,
        sources_used=list(set(s.source for s in snapshots_by_phase.values())),
        phase_coverage=list(snapshots_by_phase.keys()),
    )

def is_playable(report: DataQualityReport) -> Tuple[bool, List[str]]:
    """The Quality Gate itself."""
    if report.score < DEFAULT_THRESHOLD:
        reasons = [f"quality_score_below_threshold ({report.score}/{DEFAULT_THRESHOLD})"]
        if not report.phase_coverage:
            reasons.append("no_data_collected")
        return False, reasons
    return True, []
