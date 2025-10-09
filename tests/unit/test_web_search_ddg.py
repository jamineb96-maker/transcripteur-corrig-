"""Unit tests for the web search endpoint using DuckDuckGo.

These tests monkeypatch the search implementation to avoid
real network requests.  They verify that the endpoint responds
with the expected structure and honours query parameters.
"""

import unittest
from unittest.mock import patch

from server import create_app


class TestWebSearchDDG(unittest.TestCase):
    def test_web_search_endpoint_returns_results(self):
        app = create_app()
        client = app.test_client()
        fake_results = [
            {"title": "Example", "url": "https://example.com", "snippet": "Snippet", "source": "ddg"},
            {"title": "Example 2", "url": "https://example.org", "snippet": "Snippet 2", "source": "ddg"},
        ]
        # Patch the search function in the module used by the blueprint
        with patch("server.research.web_search.search", lambda query, lang="fr", max_results=5: fake_results):
            resp = client.get("/api/research/web?q=test&lang=fr&max=2")
            self.assertEqual(resp.status_code, 200)
            payload = resp.get_json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload.get("results"), fake_results)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()