import os

# Racines séparées par ; (Windows) ou : (POSIX). Valeur par défaut : instance/archives
PATIENTS_ARCHIVES_DIRS = os.getenv("PATIENTS_ARCHIVES_DIRS", "instance/archives")
