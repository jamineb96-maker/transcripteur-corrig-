#!/usr/bin/env pwsh

# Development script with Flask's auto‑reloader for Windows.
Set-Item -Name FLASK_APP -Value server
Set-Item -Name FLASK_ENV -Value development
python -m flask run --host 0.0.0.0 --port 5000