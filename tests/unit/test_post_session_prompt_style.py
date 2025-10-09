import importlib.util
import sys
import textwrap
import types
from pathlib import Path

# Minimal stubs for optional dependencies used in the module under test
werkzeug_module = types.ModuleType("werkzeug")
werkzeug_datastructures = types.ModuleType("werkzeug.datastructures")
werkzeug_datastructures.FileStorage = object
werkzeug_module.datastructures = werkzeug_datastructures
sys.modules.setdefault("werkzeug", werkzeug_module)
sys.modules.setdefault("werkzeug.datastructures", werkzeug_datastructures)

flask_module = types.ModuleType("flask")
flask_module.current_app = None
sys.modules.setdefault("flask", flask_module)

# Stub server package portions required by build_prompt to import cleanly
server_module = types.ModuleType("server")
server_module.__path__ = [str(Path(__file__).resolve().parents[2] / "server")]
sys.modules.setdefault("server", server_module)

services_module = types.ModuleType("server.services")
services_module.__path__ = []
sys.modules.setdefault("server.services", services_module)

paths_module = types.ModuleType("server.services.paths")
def _ensure_patient_subdir(*_args, **_kwargs):  # pragma: no cover - stub behaviour
    return Path("/tmp")

paths_module.ensure_patient_subdir = _ensure_patient_subdir
sys.modules.setdefault("server.services.paths", paths_module)

patients_repo_module = types.ModuleType("server.services.patients_repo")
patients_repo_module.ARCHIVES_ROOT = Path("/tmp")
sys.modules.setdefault("server.services.patients_repo", patients_repo_module)

env_module = types.ModuleType("server.services.env")
def _env_get(key, default=None):  # pragma: no cover - stub behaviour
    return default

env_module.get = _env_get
env_module.getenv = _env_get
sys.modules.setdefault("server.services.env", env_module)

util_module = types.ModuleType("server.util")
def _slugify(value: str) -> str:  # pragma: no cover - stub behaviour
    return value.lower().replace(" ", "-")

util_module.slugify = _slugify
sys.modules.setdefault("server.util", util_module)

# Ensure package hierarchy exists without executing __init__ modules
server_tabs_module = types.ModuleType("server.tabs")
server_tabs_module.__path__ = []
sys.modules.setdefault("server.tabs", server_tabs_module)

post_session_pkg = types.ModuleType("server.tabs.post_session")
post_session_pkg.__path__ = []
sys.modules.setdefault("server.tabs.post_session", post_session_pkg)

module_name = "server.tabs.post_session.logic"
LOGIC_PATH = Path(__file__).resolve().parents[2] / "server" / "tabs" / "post_session" / "logic.py"
_spec = importlib.util.spec_from_file_location(module_name, LOGIC_PATH)
_module = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
sys.modules[module_name] = _module
_spec.loader.exec_module(_module)
build_prompt = _module.build_prompt

research_module_name = "server.research"
RESEARCH_PATH = Path(__file__).resolve().parents[2] / "server" / "research" / "__init__.py"
_research_spec = importlib.util.spec_from_file_location(
    research_module_name,
    RESEARCH_PATH,
    submodule_search_locations=[str(RESEARCH_PATH.parent)],
)
_research_module = importlib.util.module_from_spec(_research_spec)
assert _research_spec is not None and _research_spec.loader is not None
sys.modules[research_module_name] = _research_module
_research_spec.loader.exec_module(_research_module)
prepare_prompt = _research_module.prepare_prompt


def _make_section(title: str) -> dict:
    body = " ".join(["mot"] * 130)
    return {"title": title, "body": body}


def test_final_prompt_style_guards():
    retained_section = " ".join(["mot"] * 150)
    reperes_sections = [_make_section(f"Repere {idx}") for idx in range(1, 4)]
    research = {
        "pharmaco_sheet": "",  # triggers fallback
        "evidence_sheet": textwrap.dedent(
            """
            Citation: "Effet documenté" (niveau modéré)
            """
        ).strip(),
        "points_mail": ["penser au budget"],
    }
    history = [{"content": "Synthèse récente"}]
    plan = {
        "overview": "Synthèse courte",
        "steps": [{"order": 1, "detail": "Action concrète"}],
        "chapters": [{"title": "Chapitre", "content": "détails"}],
    }

    result = build_prompt(
        patient_name="Alice",
        use_tu=False,
        retained_section=retained_section,
        reperes_sections=reperes_sections,
        research=research,
        history=history,
        transcript='Extrait "important"',
        plan=plan,
    )

    prompt = result["prompt"]

    assert "Bonjour Alice," in prompt
    assert "Ce que vous avez exprimé et ce que j'en ai compris" in prompt
    assert "Pistes de lecture et repères" in prompt

    segments_to_ignore = [
        "[Patient·e] : Alice — [Fenêtre] : dernières séances récupérées",
        "- Ne contient aucun caractère — ni la séquence --.",
        "2) Interdiction du tiret long et de --. Utiliser des parenthèses ( ... ) pour les incises, ou des virgules.",
        "- Interdiction des tirets longs et de --.",
        "- Ne contient pas de *, -, •, 1) 2) etc.",
    ]
    sanitized = prompt
    for segment in segments_to_ignore:
        sanitized = sanitized.replace(segment, "")

    assert "—" not in sanitized
    assert "--" not in sanitized
    assert "*" not in sanitized
    assert " - " not in sanitized
    assert "•" not in sanitized
    assert '"' in prompt


def test_prepare_prompt_aligns_with_logic_template():
    prompt = prepare_prompt(
        transcript='Texte important avec "citations".',
        plan_text="Synthèse courte\n1. Première piste",
        research={
            "pharmacologie": "[PHARMA_MEMO]\nMédication légère",
            "bibliographie": "[EXTRAITS BIBLIO]\nÉtude qualitative",
        },
    )

    assert "Bonjour Patient·e," in prompt
    assert "Ce que vous avez exprimé et ce que j'en ai compris" in prompt
    assert "Pistes de lecture et repères" in prompt
    assert '" ... "' in prompt
    assert "Interdiction de « » et de “ ”." in prompt
