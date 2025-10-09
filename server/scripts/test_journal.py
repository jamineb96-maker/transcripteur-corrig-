"""Script manuel pour valider le cycle CRUD du journal critique."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from server.services.journal_service import JournalService


def _print(message: str) -> None:
    sys.stdout.write(f"{message}\n")


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="journal-test-") as tmp:
            instance_path = Path(tmp)
            service = JournalService(instance_path)
            _print(f"Instance temporaire: {instance_path}")

            created = service.save_entry(
                {
                    "title": "Note de test",
                    "body_md": "## Validation\n- Vérifier la persistance",
                    "tags": ["test", "demo"],
                    "concepts": ["validation"],
                    "patients": [{"id": "demo", "name": "Patiente Demo"}],
                }
            )
            entry_id = created["id"]
            _print(f"Note créée: {entry_id}")

            items, total = service.list_entries()
            if total < 1 or not any(item.get("id") == entry_id for item in items):
                raise RuntimeError("La note créée n'apparaît pas dans l'index")
            _print(f"Total notes indexées: {total}")

            loaded = service.get_entry(entry_id)
            if not loaded or loaded.get("id") != entry_id:
                raise RuntimeError("Lecture de la note échouée")
            _print("Lecture OK")

            service.delete_entry(entry_id)
            _print("Suppression OK")

            remaining = service.reindex()
            if remaining != 0:
                raise RuntimeError(f"Réindexation attendue à 0, obtenu {remaining}")
            _print("Réindexation OK")
    except Exception as exc:  # pragma: no cover - script manuel
        sys.stderr.write(f"[journal:test] échec: {exc}\n")
        return 1
    _print("[journal:test] succès")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

