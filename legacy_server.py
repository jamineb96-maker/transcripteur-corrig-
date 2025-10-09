"""Flask backend for the assistant clinique application."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from flask import Flask, jsonify, request, send_from_directory

APP_ROOT = Path(__file__).resolve().parent
DATA_DIR_ENV = os.environ.get("CLINIC_DATA_DIR")
DATA_DIR = Path(DATA_DIR_ENV).expanduser() if DATA_DIR_ENV else APP_ROOT / "instance"
DATA_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logger.info("Application root: %s", APP_ROOT)
logger.info("Data directory: %s", DATA_DIR)

app = Flask(__name__)


def _load_patients_from_file(path: Path) -> List[Dict[str, str]]:
    try:
        if not path.exists():
            return []
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            return []
        data = json.loads(content)
        patients = data.get("patients")
        if isinstance(patients, list):
            formatted: List[Dict[str, str]] = []
            for item in patients:
                if not isinstance(item, dict):
                    continue
                patient_id = item.get("id")
                name = item.get("name")
                if isinstance(patient_id, str) and isinstance(name, str):
                    formatted.append({"id": patient_id, "name": name})
            return formatted
    except json.JSONDecodeError as exc:
        logger.error("Unable to parse patients.json: %s", exc)
    except OSError as exc:
        logger.error("Error reading patients.json: %s", exc)
    return []


def _scan_patients_from_files(directory: Path) -> List[Dict[str, str]]:
    ids = set()
    try:
        for file_path in directory.iterdir():
            if not file_path.is_file():
                continue
            name = file_path.name
            if name.endswith("_pre.txt"):
                ids.add(name[:-8])
            elif name.endswith("_post.txt"):
                ids.add(name[:-9])
    except OSError as exc:
        logger.error("Error scanning data directory %s: %s", directory, exc)
        return []
    patients = sorted(ids)
    return [
        {
            "id": patient_id,
            "name": patient_id.replace("_", " ").title(),
        }
        for patient_id in patients
    ]


def _get_patients() -> List[Dict[str, str]]:
    patients = _load_patients_from_file(DATA_DIR / "patients.json")
    if patients:
        return patients
    return _scan_patients_from_files(DATA_DIR)


def _resolve_patient_id(patient_id: Optional[str]) -> str:
    if patient_id:
        return patient_id
    patients = _get_patients()
    if patients:
        return patients[0]["id"]
    return "caroline"


def _read_patient_file(patient_id: str, suffix: str) -> str:
    filename = f"{patient_id}_{suffix}.txt"
    path = DATA_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.info("File not found for patient '%s': %s", patient_id, filename)
    except OSError as exc:
        logger.error("Error reading file %s: %s", filename, exc)
    return ""


@app.route("/api/health")
def health() -> "flask.wrappers.Response":
    return jsonify({
        "ok": True,
        "data_dir": str(DATA_DIR),
        "app_root": str(APP_ROOT),
    })


@app.route("/api/patients")
def patients() -> "flask.wrappers.Response":
    patient_list = _get_patients()
    return jsonify({"patients": patient_list})


@app.route("/api/pre-session")
def pre_session() -> "flask.wrappers.Response":
    patient_id = _resolve_patient_id(request.args.get("patient_id"))
    content = _read_patient_file(patient_id, "pre")
    return jsonify({"patient_id": patient_id, "content": content})


@app.route("/api/post-session")
def post_session() -> "flask.wrappers.Response":
    patient_id = _resolve_patient_id(request.args.get("patient_id"))
    content = _read_patient_file(patient_id, "post")
    return jsonify({"patient_id": patient_id, "content": content})


@app.route("/")
def root() -> "flask.wrappers.Response":
    return send_from_directory(APP_ROOT, "index.html")


@app.route("/app.js")
def app_js() -> "flask.wrappers.Response":
    return send_from_directory(APP_ROOT, "app.js")


@app.route("/styles.css")
def styles_css() -> "flask.wrappers.Response":
    return send_from_directory(APP_ROOT, "styles.css")


if __name__ == "__main__":
    host = os.environ.get("CLINIC_HOST", "127.0.0.1")
    port = int(os.environ.get("CLINIC_PORT", "1421"))
    logger.info("Starting server on %s:%s", host, port)
    app.run(host=host, port=port)
