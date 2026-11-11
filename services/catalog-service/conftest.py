"""pytest configuration for catalog-service tests."""
import sys
from pathlib import Path

# Add catalog-service directory so catalog_app is importable
sys.path.insert(0, str(Path(__file__).parent))
