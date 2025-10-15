"""Course runner - executes analysis for a single race."""
import logging
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from config import Config

logger = logging.getLogger(__name__)


class CourseRunner:
    """Execute race analysis using runner_chain.py."""
    
    def __init__(self, config: Config):
        self.config = config
    
    def run_course(
        self,
        course_url: str,
        phase: str,
        date: str,
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run analysis for one course at given phase (H30 or H5).
        
        Uses runner_chain.py with minimal planning file for single course.
        
        Returns result dict with status, artifacts, etc.
        """
        logger.info(f"Running {course_url} phase={phase}", extra={
            "correlation_id": correlation_id
        })
        
        # Normalize phase
        phase_norm = phase.upper().replace("-", "")
        if phase_norm not in ["H30", "H5"]:
            return {
                "ok": False,
                "error": f"Invalid phase: {phase}",
                "course_url": course_url
            }
        
        # Extract R/C from URL
        try:
            rc_match = self._extract_rc_from_url(course_url)
            if not rc_match:
                return {
                    "ok": False,
                    "error": "Cannot extract R/C from URL",
                    "course_url": course_url
                }
            
            r_label, c_label = rc_match
            race_id = f"{r_label}{c_label}"
            
        except Exception as e:
            return {
                "ok": False,
                "error": f"Failed to parse URL: {e}",
                "course_url": course_url
            }
        
        # Create minimal planning file for runner_chain.py
        try:
            planning = self._create_planning_file(
                date, r_label, c_label, race_id, course_url
            )
        except Exception as e:
            logger.error(f"Failed to create planning: {e}", exc_info=True)
            return {
                "ok": False,
                "error": f"Planning creation failed: {e}",
                "course_url": course_url
            }
        
        # Run runner_chain.py
        try:
            result = self._run_runner_chain(planning, phase_norm, race_id)
            
            # Upload artifacts to GCS if configured
            if self.config.GCS_BUCKET and result.get("ok"):
                self._upload_artifacts(race_id, date)
            
            return result
            
        except Exception as e:
            logger.error(f"Runner chain failed: {e}", exc_info=True)
            return {
                "ok": False,
                "error": str(e),
                "course_url": course_url,
                "rc": race_id
            }
        finally:
            # Cleanup planning file
            try:
                Path(planning).unlink(missing_ok=True)
            except:
                pass
    
    def _extract_rc_from_url(self, url: str) -> Optional[tuple]:
        """Extract (R#, C#) from ZEturf URL."""
        import re
        match = re.search(r'/(R\d+)(C\d+)[-/]', url)
        if match:
            return match.group(1), match.group(2)
        return None
    
    def _create_planning_file(
        self,
        date: str,
        r_label: str,
        c_label: str,
        race_id: str,
        course_url: str
    ) -> str:
        """Create minimal planning JSON for single race."""
        
        # Generate course_id (can be any unique value)
        course_id = f"{date.replace('-', '')}{race_id}"
        
        planning_data = [
            {
                "id": race_id,
                "id_course": course_id,
                "reunion": r_label,
                "course": c_label,
                "start": f"{date}T12:00:00+01:00",  # Dummy time
                "url": course_url
            }
        ]
        
        # Write to temp file
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.json',
            delete=False
        ) as f:
            json.dump(planning_data, f, ensure_ascii=False, indent=2)
            return f.name
    
    def _run_runner_chain(
        self,
        planning_file: str,
        phase: str,
        race_id: str
    ) -> Dict[str, Any]:
        """Execute runner_chain.py subprocess."""
        
        # Determine window based on phase
        if phase == "H30":
            h30_min, h30_max = -9999, 9999  # Always run
            h5_min, h5_max = 9999, 9999  # Never run
        else:  # H5
            h30_min, h30_max = 9999, 9999  # Never run
            h5_min, h5_max = -9999, 9999  # Always run
        
        cmd = [
            "python", "scripts/runner_chain.py",
            "--planning", planning_file,
            "--data-dir", self.config.DATA_DIR,
            "--budget", str(self.config.BUDGET),
            "--ev-min", str(self.config.EV_MIN),
            "--roi-min", str(self.config.ROI_MIN),
            "--calibration", str(self.config.CALIBRATION_PATH),
            "--h30-window-min", str(h30_min),
            "--h30-window-max", str(h30_max),
            "--h5-window-min", str(h5_min),
            "--h5-window-max", str(h5_max),
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes max
                check=False
            )
            
            stdout = result.stdout
            stderr = result.stderr
            rc = result.returncode
            
            # Log output
            if stdout:
                logger.info(f"Runner stdout (last 500 chars): {stdout[-500:]}")
            if stderr:
                logger.warning(f"Runner stderr: {stderr}")
            
            # Find artifacts
            race_dir = Path(self.config.DATA_DIR) / race_id
            artifacts = self._collect_artifacts(race_dir)
            
            return {
                "ok": rc == 0,
                "rc": rc,
                "race_id": race_id,
                "phase": phase,
                "stdout_tail": stdout[-500:] if stdout else "",
                "stderr_tail": stderr[-500:] if stderr else "",
                "artifacts": artifacts
            }
            
        except subprocess.TimeoutExpired:
            logger.error(f"Runner timeout for {race_id}")
            return {
                "ok": False,
                "error": "timeout",
                "race_id": race_id
            }
        except Exception as e:
            logger.error(f"Runner execution failed: {e}", exc_info=True)
            return {
                "ok": False,
                "error": str(e),
                "race_id": race_id
            }
    
    def _collect_artifacts(self, race_dir: Path) -> Dict[str, str]:
        """Collect paths to generated artifacts."""
        artifacts = {}
        
        if not race_dir.exists():
            return artifacts
        
        for name in [
            "analysis.json",
            "metrics.json",
            "metrics.csv",
            "p_finale.json",
            "tickets.json",
            "snapshot_H30.json",
            "snapshot_H5.json",
            "h30.json",
            "h5.json"
        ]:
            path = race_dir / name
            if path.exists():
                artifacts[name] = str(path)
        
        return artifacts
    
    def _upload_artifacts(self, race_id: str, date: str) -> None:
        """Upload artifacts to GCS."""
        try:
            from google.cloud import storage
            
            client = storage.Client(project=self.config.PROJECT_ID)
            bucket = client.bucket(self.config.GCS_BUCKET)
            
            race_dir = Path(self.config.DATA_DIR) / race_id
            
            for file_path in race_dir.glob("*.json"):
                blob_name = f"{self.config.GCS_PREFIX}/analyses/{date}/{race_id}/{file_path.name}"
                blob = bucket.blob(blob_name)
                blob.upload_from_filename(str(file_path))
                logger.info(f"Uploaded {file_path.name} to gs://{self.config.GCS_BUCKET}/{blob_name}")
            
            for file_path in race_dir.glob("*.csv"):
                blob_name = f"{self.config.GCS_PREFIX}/analyses/{date}/{race_id}/{file_path.name}"
                blob = bucket.blob(blob_name)
                blob.upload_from_filename(str(file_path))
                logger.info(f"Uploaded {file_path.name} to gs://{self.config.GCS_BUCKET}/{blob_name}")
                
        except Exception as e:
            logger.warning(f"GCS upload failed: {e}")
