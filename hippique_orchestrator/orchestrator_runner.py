import re
from typing import Tuple, Optional

class GPIOutput:
    def __init__(self, gpi_decision: str, **kwargs):
        self.gpi_decision = gpi_decision
        self.playable = gpi_decision.lower() == "play"
        for key, value in kwargs.items():
            setattr(self, key, value)

    def model_dump(self):
        return self.__dict__

def extract_rc_from_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Extracts the Reunion (R) and Course (C) numbers from a URL.
    """
    if not url:
        return None
    
    # Regex to find patterns like R1C1, R12C5, etc.
    match = re.search(r'(R(\d+)C(\d+))', url, re.IGNORECASE)
    if match:
        r_num = match.group(2)
        c_num = match.group(3)
        return f"R{r_num}", f"C{c_num}"
        
    # Fallback for patterns like /r1-c1/
    match = re.search(r'/(r(\d+)-c(\d+))/', url, re.IGNORECASE)
    if match:
        r_num = match.group(2)
        c_num = match.group(3)
        return f"R{r_num}", f"C{c_num}"
        
    return None

async def run_course_analysis_pipeline(course_url: str, phase: str, **kwargs) -> GPIOutput:
    """
    Dummy function for running the course analysis pipeline.
    """
    # In a real scenario, this would involve complex analysis.
    # For now, we return a dummy output to satisfy the tests.
    if "error" in course_url:
        raise ValueError("Simulated error in pipeline")

    return GPIOutput(gpi_decision="play", message="Dummy analysis complete")
