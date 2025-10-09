from __future__ import annotations

import os
import sys
from typing import Generator

import pytest

pytest.importorskip("flask")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server import create_app


@pytest.fixture()
def client() -> Generator:
  app = create_app()
  app.config.update({"TESTING": True})
  with app.test_client() as test_client:
      yield test_client


def test_mail_sections_generated(client) -> None:
  transcript = (
      "Séance centrée sur la préparation du retour au travail,"
      " identification des contraintes structurelles et soutien aux ajustements concrets."
  )

  plan_response = client.post(
      "/api/post-session/plan",
      json={"transcript": transcript},
  )
  assert plan_response.status_code == 200
  plan_payload = plan_response.get_json()
  assert plan_payload["ok"] is True
  plan_text = plan_payload["plan"]

  mail_response = client.post(
      "/api/post-session/mail",
      json={
          "transcript": transcript,
          "plan": plan_text,
      },
  )

  assert mail_response.status_code == 200
  payload = mail_response.get_json()
  assert payload["ok"] is True
  assert "Ce que j’ai retenu" in payload["resume_seance"]
  assert payload["pistes_lectures_repere"].strip()
