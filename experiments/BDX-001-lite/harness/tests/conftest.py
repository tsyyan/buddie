import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                       # bdx
sys.path.insert(0, str(HERE.parents[1] / "evaluation"))     # evaluate (evaluation tests only)
