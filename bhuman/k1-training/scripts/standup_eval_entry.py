"""Supply the managed run directory before executing the evaluation CLI."""
import os
from pathlib import Path
import runpy
import sys

script = Path(__file__).with_name("evaluate_standup.py")
sys.argv = [str(script)] + sys.argv[1:] + ["--output", os.environ["BH_RUN_DIR"]]
runpy.run_path(str(script), run_name="__main__")
