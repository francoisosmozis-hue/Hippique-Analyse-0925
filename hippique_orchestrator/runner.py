"""
src/hippique_orchestrator/runner.py - Orchestrator for the Firestore-native analysis pipeline.
"""

from __future__ import annotations

import re
from typing import Any

# Import the refactored, Firestore-native analysis pipeline
# Assuming analyse_courses_du_jour_enrichie is at the root level and is importable.
# This might need adjustment based on final project structure.
from hippique_orchestrator import analysis_pipeline

from hippique_orchestrator.config import get_config
from hippique_orchestrator.logging_utils import get_logger

logger = get_logger(__name__)
config = get_config()

def _extract_rc_from_url(course_url: str) -> tuple[str, str]:
    """
    Extracts Reunion and Course numbers from a ZEturf-like URL.
    """
    match = re.search(r"/R(\d+)C(\d+)", course_url, re.IGNORECASE)
    if not match:
        raise ValueError(f"Cannot extract R/C from URL: {course_url}")
    r_num, c_num = match.groups()
    return f"R{int(r_num)}", f"C{int(c_num)}"


def run_course(
    course_url: str,
    phase: str,
    date: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """
    Executes the analysis for a single course by calling the Firestore-native pipeline.
    This function is now a high-level orchestrator that delegates to the analysis module.
    """
    phase_clean = phase.upper().replace("-", "")
    
    try:
        reunion, course = _extract_rc_from_url(course_url)
    except ValueError as e:
        logger.error(str(e), correlation_id=correlation_id)
        return {"ok": False, "error": str(e)}

    logger.info(
        "Starting Firestore-native course analysis",
        correlation_id=correlation_id,
        reunion=reunion,
        course=course,
        phase=phase_clean,
        date=date,
    )

    try:
        # Get budget from the central configuration
        budget = config.budget_total

        # Delegate directly to the refactored analysis function
        result = analysis_pipeline.process_single_course_analysis(
            reunion=reunion,
            course=course,
            phase=phase_clean,
            date=date,
            budget=budget,
        )

        if result.get("success"):
            logger.info(
                "Course analysis completed successfully.",
                correlation_id=correlation_id,
                race_doc_id=result.get("race_doc_id"),
                analysis_result=result.get("analysis_result")
            )
            return {
                "ok": True,
                "phase": phase_clean,
                "analysis": result.get("analysis_result")
            }
        else:
            logger.error(
                "Course analysis failed.",
                correlation_id=correlation_id,
                error_message=result.get("message"),
                race_doc_id=result.get("race_doc_id"),
            )
            return {
                "ok": False,
                "phase": phase_clean,
                "error": result.get("message"),
            }

    except Exception as e:
        logger.exception(
            "An unexpected error occurred during course analysis.",
            correlation_id=correlation_id,
            reunion=reunion,
            course=course,
        )
        return {
            "ok": False,
            "phase": phase_clean,
            "error": f"An unexpected exception occurred: {e}",
        }
