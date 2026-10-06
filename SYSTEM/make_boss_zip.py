from pathlib import Path
import runpy
import sys
sys.path.insert(0, str(Path.home()/"DEVCO_FIELD/SYSTEM"))
runpy.run_path(str(Path.home()/"DEVCO_FIELD/SYSTEM/project_directory.py"), run_name="__main__")
