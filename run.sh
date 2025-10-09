#!/bin/bash

# Simple runner for the post‑session assistant.
#
# This script starts the Flask server on port 5000.  It assumes that the
# dependencies are installed (see requirements.txt).  To install them in a
# virtual environment, run:
#
#   python3 -m venv .venv
#   source .venv/bin/activate
#   pip install -r requirements.txt
#
# Then execute this script.

set -e

python3 -m server --host 0.0.0.0 --port 5000