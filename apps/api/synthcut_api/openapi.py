"""Print the OpenAPI document (``python -m synthcut_api.openapi > docs/openapi.json``).
The Mini App's TypeScript types are generated from it."""

from __future__ import annotations

import json

from synthcut_core.settings import Settings

from .main import create_app


def main() -> None:
    print(json.dumps(create_app(Settings()).openapi(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
