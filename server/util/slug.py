import unicodedata, re

def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii","ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+","-", s).strip("-").lower()
    return s or "patient"
