$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$here\.venv\Scripts\Activate.ps1"
python "$here\server\run.py"
