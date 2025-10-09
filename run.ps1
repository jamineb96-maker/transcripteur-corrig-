#!/usr/bin/env pwsh

# PowerShell script to start the post‑session assistant on Windows.
# Ensure that Python and the required packages are available.  To install
# dependencies into a virtual environment, you can run:
#
#   python -m venv .venv
#   .\.venv\Scripts\Activate.ps1
#   pip install -r requirements.txt
#
# Then run this script.

python -m server --host 0.0.0.0 --port 5000