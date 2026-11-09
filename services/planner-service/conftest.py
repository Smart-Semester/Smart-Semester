"""pytest configuration for planner-service tests.

Adds the service's app directory to sys.path so that
`from app.schemas import ...` resolves correctly when tests are run
from the repo root or from within the service directory.
"""
import sys
from pathlib import Path

# Insert the directory that *contains* the `app` package
sys.path.insert(0, str(Path(__file__).parent / "app" / ".."))
