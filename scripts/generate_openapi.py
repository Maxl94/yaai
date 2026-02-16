#!/usr/bin/env python3
"""Export the FastAPI OpenAPI schema to a JSON file.

Usage:
    python scripts/generate_openapi.py [output_path]

Generates the OpenAPI JSON without starting the server or connecting
to any database. The lifespan handler is NOT invoked -- only the
route metadata is read.
"""

import json
import sys
from pathlib import Path

from yaai.server.main import app


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/openapi.json")
    output.parent.mkdir(parents=True, exist_ok=True)

    schema = app.openapi()
    output.write_text(json.dumps(schema, indent=2))
    print(f"OpenAPI schema written to {output}")


if __name__ == "__main__":
    main()
