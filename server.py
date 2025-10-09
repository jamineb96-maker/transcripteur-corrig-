"""Point d'entrée exécutable pour lancer l'application Flask."""

from __future__ import annotations

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(), override=True)

import logging
import os

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("[env] OPENAI_API_KEY manquante")

from config import settings

from server import create_app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )

    app = create_app()

    host = os.getenv("HOST", settings.HOST)
    try:
        port = int(os.getenv("PORT", str(settings.PORT)))
    except ValueError:
        port = settings.PORT
    debug_flag = os.getenv("FLASK_DEBUG", settings.FLASK_DEBUG_FLAG)
    debug = debug_flag in {"1", "true", "True"}

    print(f"[env] OPENAI_API_KEY loaded: {bool(os.getenv('OPENAI_API_KEY'))}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()

