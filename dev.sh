#!/bin/bash

# Development runner with auto‑reload using Flask's built‑in reloader.
# Requires the 'flask' package.  You can set FLASK_DEBUG=1 to enable
# debugging.

export FLASK_APP=server
export FLASK_ENV=development

python3 -m flask run --host 0.0.0.0 --port 5000