"""Point d'entrée pour lancer l'application Flask.

Ce module instancie l'application via la fabrique `create_app()` et
utilise la configuration pour déterminer le port d'écoute.  Il est
conçu pour être exécuté directement par les scripts de démarrage.
"""

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(), override=True)

import os
import sys

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("[env] OPENAI_API_KEY manquante")

# Ajoute le répertoire racine du projet au sys.path pour permettre les imports absolus.
current_dir = os.path.dirname(os.path.abspath(__file__))
base_dir = os.path.dirname(current_dir)
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

from server import create_app  # type: ignore
from server.services.env import env


def main() -> None:
    """Instancie et lance l'application Flask."""
    app = create_app()

    # Utilise la variable d'environnement APP_PORT ou 1421 par défaut
    port = int(env('APP_PORT', 1421))
    print(f"[env] OPENAI_API_KEY loaded: {bool(os.getenv('OPENAI_API_KEY'))}")
    # Écoute uniquement sur localhost; debug activé pour un démarrage rapide
    app.run(host='127.0.0.1', port=port, debug=True)


if __name__ == '__main__':
    main()