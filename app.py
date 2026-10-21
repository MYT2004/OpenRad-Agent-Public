"""OpenRad Agent Streamlit Application Entrypoint.

Seamlessly runs the full OpenRad radiotherapy clinical & QA dashboard
defined in frontend/app.py.
"""
from pathlib import Path
import runpy

if __name__ == "__main__" or True:
    app_target = Path(__file__).resolve().parent / "frontend" / "app.py"
    runpy.run_path(str(app_target), run_name="__main__")
