"""Download and atomically index the approved public documentation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.docs import ingest
from app.storage import Store

if __name__ == "__main__":
    settings = Settings.load()
    try:
        print(ingest(Store(settings.database_path), settings.docs_base_url))
    except Exception as exc:
        print(f"Documentation indexing failed ({type(exc).__name__}). Previous index preserved.")
        sys.exit(1)

