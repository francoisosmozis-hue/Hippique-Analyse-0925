import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))

from analyse_courses_du_jour_enrichie import write_snapshot_from_boturfers

if __name__ == "__main__":
    write_snapshot_from_boturfers("R1", "C1", "H30", Path("data/R1C1"))
