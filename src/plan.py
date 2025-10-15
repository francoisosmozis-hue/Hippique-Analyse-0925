"""Build daily race plan from ZEturf + Geny."""
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import subprocess
import tempfile

logger = logging.getLogger(__name__)


def build_plan(date: str) -> List[Dict[str, Any]]:
    """
    Build race plan for date (YYYY-MM-DD).
    
    Returns list of races: [{date, r_label, c_label, meeting, time_local, course_url, reunion_url}]
    
    Uses:
    1. fetch_reunions_geny.py to get meetings list
    2. online_fetch_zeturf.py --mode planning to get full schedule with times
    """
    logger.info(f"Building plan for {date}")
    
    # Step 1: Get reunions from Geny (for list of meetings)
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            tmp_path = tmp.name
        
        cmd = [
            "python", "scripts/fetch_reunions_geny.py",
            "--date", date,
            "--out", tmp_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logger.error(f"fetch_reunions_geny failed: {result.stderr}")
            return []
        
        with open(tmp_path, 'r', encoding='utf-8') as f:
            geny_data = json.load(f)
        
        reunions = geny_data.get("reunions", [])
        logger.info(f"Found {len(reunions)} reunions from Geny")
        
    except Exception as e:
        logger.error(f"Failed to fetch Geny reunions: {e}", exc_info=True)
        return []
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except:
            pass
    
    # Step 2: Get full planning from ZEturf (with times)
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            planning_path = tmp.name
        
        cmd = [
            "python", "scripts/online_fetch_zeturf.py",
            "--mode", "planning",
            "--date", date,
            "--out", planning_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            logger.warning(f"ZEturf planning failed: {result.stderr}")
            # Fallback to Geny only
            return _build_from_geny_only(reunions, date)
        
        with open(planning_path, 'r', encoding='utf-8') as f:
            planning_data = json.load(f)
        
        # Parse planning to extract races
        races = []
        for entry in planning_data:
            try:
                race = _parse_planning_entry(entry, date)
                if race:
                    races.append(race)
            except Exception as e:
                logger.warning(f"Failed to parse entry: {e}")
                continue
        
        logger.info(f"Built plan with {len(races)} races")
        return races
        
    except Exception as e:
        logger.error(f"Failed to build planning from ZEturf: {e}", exc_info=True)
        return _build_from_geny_only(reunions, date)
    finally:
        try:
            Path(planning_path).unlink(missing_ok=True)
        except:
            pass


def _parse_planning_entry(entry: Dict[str, Any], date: str) -> Optional[Dict[str, Any]]:
    """Parse a planning entry into normalized race dict."""
    
    # Extract RC labels
    rc_label = entry.get("id") or entry.get("rc") or ""
    match = re.match(r"^(R\d+)(C\d+)$", str(rc_label).upper())
    if not match:
        return None
    
    r_label = match.group(1)
    c_label = match.group(2)
    
    # Get time
    time_local = entry.get("time") or entry.get("start") or entry.get("start_time")
    if time_local and "T" in time_local:
        # Parse ISO format
        dt = datetime.fromisoformat(time_local.replace("Z", "+00:00"))
        time_local = dt.strftime("%H:%M")
    
    # Build URLs
    meeting = entry.get("hippodrome") or entry.get("meeting", "")
    meeting_slug = _slugify(meeting)
    
    course_url = f"https://www.zeturf.fr/fr/course/{date}/{r_label}{c_label}-{meeting_slug}"
    reunion_url = f"https://www.zeturf.fr/fr/reunion/{date}/{r_label}-{meeting_slug}"
    
    return {
        "date": date,
        "r_label": r_label,
        "c_label": c_label,
        "meeting": meeting,
        "time_local": time_local,
        "course_url": course_url,
        "reunion_url": reunion_url
    }


def _build_from_geny_only(reunions: List[Dict], date: str) -> List[Dict[str, Any]]:
    """Fallback: build plan from Geny reunions only (no times)."""
    logger.warning("Building plan from Geny only (no times available)")
    
    races = []
    for reunion in reunions:
        r_label = reunion.get("label", "")
        if not r_label.startswith("R"):
            continue
        
        meeting = reunion.get("hippodrome", "")
        meeting_slug = _slugify(meeting)
        reunion_url = f"https://www.zeturf.fr/fr/reunion/{date}/{r_label}-{meeting_slug}"
        
        # Default to 10 courses per reunion
        for c_num in range(1, 11):
            c_label = f"C{c_num}"
            course_url = f"https://www.zeturf.fr/fr/course/{date}/{r_label}{c_label}-{meeting_slug}"
            
            races.append({
                "date": date,
                "r_label": r_label,
                "c_label": c_label,
                "meeting": meeting,
                "time_local": None,  # Unknown
                "course_url": course_url,
                "reunion_url": reunion_url
            })
    
    return races


def _slugify(text: str) -> str:
    """Convert text to URL slug."""
    import unicodedata
    
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^\w\s-]', '', text.lower())
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')
