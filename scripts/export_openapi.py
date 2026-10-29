"""Write openapi.json (needs no portal access)."""
import json
from pathlib import Path

from app.main import app

Path("openapi.json").write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
print("wrote openapi.json")
