#!/usr/bin/env bash
set -eEuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

readonly PORT="${PORT:-1421}"
readonly FLASK_ENVIRONMENT="${FLASK_ENV:-production}"

pause_for_user() {
  if [[ -t 0 ]]; then
    echo
    read -rp "Appuyez sur Entrée pour fermer cette fenêtre..." _ </dev/tty || true
  fi
}

handle_exit() {
  local status=$?
  if [[ $status -ne 0 ]]; then
    echo "\n[ERREUR] Le script s'est arrêté avec le code $status." >&2
  fi
  pause_for_user
}

trap handle_exit EXIT
trap 'echo "[ERREUR] Commande échouée: ${BASH_COMMAND}" >&2' ERR

install_system_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    local packages=(
      python3-venv python3-dev build-essential pkg-config
      libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0
      libjpeg-dev zlib1g-dev libfreetype6-dev liblcms2-dev
      libffi-dev libxml2-dev libxslt1-dev libharfbuzz0b libfribidi0
      libqpdf-dev
    )

    local missing=()
    for pkg in "${packages[@]}"; do
      dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
    done

    if ((${#missing[@]} > 0)); then
      echo "[INFO] Installation des dépendances système: ${missing[*]}"
      if ((EUID != 0)) && command -v sudo >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y "${missing[@]}"
      elif ((EUID == 0)); then
        apt-get update
        apt-get install -y "${missing[@]}"
      else
        echo "[AVERTISSEMENT] Exécutez ce script avec sudo ou installez manuellement: ${missing[*]}" >&2
      fi
    fi
  fi
}

install_system_packages

if [[ ! -d .venv ]]; then
  echo "[INFO] Création de l'environnement virtuel..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

python -m compileall server

export PORT
export FLASK_ENV="$FLASK_ENVIRONMENT"

launch_firefox() {
  local url="http://127.0.0.1:${PORT}"
  if command -v firefox >/dev/null 2>&1; then
    echo "[INFO] Ouverture de Firefox sur ${url}"
    firefox --new-tab "$url" >/dev/null 2>&1 &
  elif command -v xdg-open >/dev/null 2>&1; then
    echo "[AVERTISSEMENT] Firefox introuvable, ouverture via xdg-open."
    xdg-open "$url" >/dev/null 2>&1 &
  else
    echo "[AVERTISSEMENT] Impossible d'ouvrir le navigateur automatiquement. Rendez-vous sur ${url}" >&2
  fi
}

wait_for_server() {
  python - "$PORT" <<'PY'
import socket
import sys
import time

port = int(sys.argv[1])
for _ in range(60):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            sys.exit(0)
    time.sleep(0.5)
print("Le serveur ne semble pas avoir démarré à temps.", file=sys.stderr)
sys.exit(1)
PY
}

python server.py &
server_pid=$!

if wait_for_server; then
  launch_firefox
else
  echo "[AVERTISSEMENT] Le serveur n'a pas répondu à temps, le navigateur ne sera pas lancé." >&2
fi

wait "$server_pid"
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt
python -m compileall server

export PORT=1421
export FLASK_ENV=production

python server.py
