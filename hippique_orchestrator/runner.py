"""
src/hippique_orchestrator/runner.py - Orchestrator for the Firestore-native analysis pipeline.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from hippique_orchestrator import analysis_pipeline, config

logger = logging.getLogger(__name__)


def _extract_rc_from_url(course_url: str) -> tuple[str, str]:
    """
    Extracts Reunion and Course numbers from a URL (Boturfers or ZEturf-like).
    """
    # Prioritize ZEturf-like format like "/R1C2"
    zeturf_match = re.search(r"/R(\d+)C(\d+)", course_url, re.IGNORECASE)
    if zeturf_match:
        r_num, c_num = zeturf_match.groups()
        return f"R{int(r_num)}", f"C{int(c_num)}"

    # Fallback to Boturfers format like "...-r2c2-..."
    boturfers_match = re.search(r"r(\d+)c(\d+)", course_url, re.IGNORECASE)
    if boturfers_match:
        r_num, c_num = boturfers_match.groups()
        return f"R{int(r_num)}", f"C{int(c_num)}"

    raise ValueError(f"Cannot extract R/C from URL: {course_url}")


async def run_course(
    course_url: str,
    phase: str,
    date: str,
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """
    Executes the analysis for a single course by calling the Firestore-native pipeline.
    This function is now a high-level orchestrator that delegates to the analysis module.
    """
    phase_clean = phase.upper().replace("-", "")

    try:
        reunion, course = _extract_rc_from_url(course_url)
    except ValueError as e:
        logger.error(str(e), extra={"correlation_id": correlation_id, "trace_id": trace_id})
        return {"ok": False, "error": str(e)}

    logger.info(
        "Starting Firestore-native course analysis",
        extra={
            "correlation_id": correlation_id,
            "trace_id": trace_id,
            "reunion": reunion,
            "course": course,
            "phase": phase_clean,
            "date": date,
        },
    )

    try:
        # Get budget from the central configuration
        # budget = config.BUDGET_CAP_EUR

        # Delegate directly to the refactored analysis function
        result = await analysis_pipeline.run_analysis_for_phase(
            course_url=course_url,
            phase=phase_clean,
            date=date,
            # race_doc_id is handled internally by run_analysis_for_phase
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

        if result.get("success"):
            logger.info(
                "Course analysis completed successfully.",
                extra={
                    "correlation_id": correlation_id,
                    "trace_id": trace_id,
                    "race_doc_id": result.get("race_doc_id"),
                    "analysis_result": result.get("analysis_result"),
                },
            )
            return {"ok": True, "phase": phase_clean, "analysis": result.get("analysis_result")}
        else:
            logger.error(
                "Course analysis failed.",
                extra={
                    "correlation_id": correlation_id,
                    "trace_id": trace_id,
                    "error_message": result.get("message"),
                    "race_doc_id": result.get("race_doc_id"),
                },
            )
            return {
                "ok": False,
                "phase": phase_clean,
                "error": result.get("message"),
            }

    except Exception as e:
        logger.error(  # Changed from logger.exception
            "An unexpected error occurred during course analysis.",
            exc_info=e,  # Added exc_info=e
            extra={
                "correlation_id": correlation_id,
                "trace_id": trace_id,
                "reunion": reunion,
                "course": course,
            },
        )
        return {
            "ok": False,
            "phase": phase_clean,
            "error": f"An unexpected exception occurred: {e}",
        }
