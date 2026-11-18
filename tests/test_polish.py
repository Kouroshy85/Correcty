"""Polish Text: prompts, AI settings and the Ollama client (Ollama itself is faked)."""
import shutil
import tempfile
import unittest
from unittest import mock

from correcty import create_app
from correcty import polish as polisher


def fake_ollama(reply="Polished text.", models=("qwen3:4b-instruct",), template="<|im_start|>assistant\n", calls=None):
    """Stand-in for polisher._request that records chat payloads."""

    def _request(url, path, payload=None, timeout=5):
        if path == "/api/version":
            return {"version": "0.40.6"}
        if path == "/api/tags":
            return {"models": [{"name": m} for m in models]}
        if path == "/api/show":
            return {"template": template}
        if path == "/api/chat":
            if calls is not None:
                calls.append(payload)
            if isinstance(reply, Exception):
                raise reply
            return {"message": {"content": reply}}
        raise AssertionError(path)

    return _request


class PolishTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = create_app({"DATA_DIR": self.tmp, "SEED_EXAMPLES": False}).test_client()
        polisher._thinking_cache.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class PromptApiTests(PolishTestCase):
    def test_default_prompt_is_seeded_and_active(self):
        prompts = self.client.get("/api/prompts").get_json()["prompts"]
        self.assertEqual(len(prompts), 1)
        self.assertTrue(prompts[0]["active"])

    def test_create_update_activate_delete(self):
        r = self.client.post("/api/prompts", json={"name": "Formal", "prompt": "Be formal."})
        self.assertEqual(r.status_code, 201)
        new = r.get_json()["prompt"]
        self.assertFalse(new["active"])

        r = self.client.put(f"/api/prompts/{new['id']}", json={"name": "Very formal", "prompt": "Be very formal."})
        self.assertEqual(r.get_json()["prompt"]["name"], "Very formal")

        prompts = self.client.post(f"/api/prompts/{new['id']}/activate", json={}).get_json()["prompts"]
        self.assertEqual([p["id"] for p in prompts if p["active"]], [new["id"]])  # only one active

        self.assertEqual(self.client.delete(f"/api/prompts/{new['id']}").status_code, 204)
        self.assertEqual(self.client.post(f"/api/prompts/{new['id']}/activate", json={}).status_code, 404)

    def test_creating_an_active_prompt_deactivates_others(self):
        self.client.post("/api/prompts", json={"name": "B", "prompt": "b", "active": True})
        active = [p["name"] for p in self.client.get("/api/prompts").get_json()["prompts"] if p["active"]]
        self.assertEqual(active, ["B"])

    def test_validation(self):
        r = self.client.post("/api/prompts", json={"name": " ", "prompt": ""})
        self.assertEqual(r.status_code, 422)
        codes = {f["code"] for f in r.get_json()["error"]["fields"]}
        self.assertEqual(codes, {"prompt_name_required", "prompt_text_required"})

    def test_settings_page_renders(self):
        self.assertEqual(self.client.get("/settings").status_code, 200)
        self.assertEqual(self.client.get("/settings?tab=ai").status_code, 200)


class AiSettingsTests(PolishTestCase):
    def test_only_local_addresses_are_allowed(self):
        for url in ["http://example.com:11434", "http://10.0.0.5:11434", "ftp://127.0.0.1", "http://127.0.0.1:11434/x"]:
            with self.subTest(url=url):
                r = self.client.put("/api/ai/settings", json={"ollama_url": url, "model": "qwen3:4b-instruct"})
                self.assertEqual(r.status_code, 422)
        with mock.patch.object(polisher, "_request", fake_ollama()):
            r = self.client.put("/api/ai/settings", json={"ollama_url": "http://localhost:11434/", "model": "qwen3:4b-instruct"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["ollama_url"], "http://localhost:11434")

    def test_status(self):
        with mock.patch.object(polisher, "_request", fake_ollama()):
            status = self.client.get("/api/ai/status").get_json()
        self.assertTrue(status["reachable"] and status["model_installed"])
        self.assertFalse(status["thinking_only"])

    def test_status_when_ollama_is_off(self):
        def offline(*args, **kwargs):
            raise polisher.PolishError("ollama_unavailable")

        with mock.patch.object(polisher, "_request", offline):
            status = self.client.get("/api/ai/status").get_json()
        self.assertFalse(status["reachable"])


class PolishApiTests(PolishTestCase):
    def test_polish_uses_active_prompt_and_keeps_language(self):
        calls = []
        self.client.post("/api/prompts", json={"name": "Formal", "prompt": "Be very formal.", "active": True})
        with mock.patch.object(polisher, "_request", fake_ollama(reply="«متن مرتب‌شده»", calls=calls)):
            r = self.client.post("/api/polish", json={"text": "سلام لینک رو فرستادم"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["text"], "متن مرتب‌شده")  # wrapping quotes removed
        self.assertEqual(r.get_json()["prompt"], "Formal")
        system = calls[0]["messages"][0]["content"]
        self.assertIn("Be very formal.", system)
        self.assertIn("Persian (Farsi)", system)
        self.assertIn("{{ }}", system)
        self.assertEqual(calls[0]["messages"][1]["content"], "سلام لینک رو فرستادم")
        self.assertEqual(calls[0]["model"], "qwen3:4b-instruct")

    def test_english_text_is_marked_english(self):
        calls = []
        with mock.patch.object(polisher, "_request", fake_ollama(calls=calls)):
            self.client.post("/api/polish", json={"text": "hi, ur class is at 5"})
        self.assertIn("written in English", calls[0]["messages"][0]["content"])

    def test_think_tags_are_removed(self):
        with mock.patch.object(polisher, "_request", fake_ollama(reply="<think>hmm</think>\nHello!")):
            self.assertEqual(self.client.post("/api/polish", json={"text": "hello"}).get_json()["text"], "Hello!")

    def test_empty_and_too_long(self):
        self.assertEqual(self.client.post("/api/polish", json={"text": "   "}).status_code, 400)
        r = self.client.post("/api/polish", json={"text": "x" * (polisher.MAX_TEXT + 1)})
        self.assertEqual(r.get_json()["error"]["code"], "polish_too_long")

    def test_ollama_errors_are_explained(self):
        cases = [
            (polisher.PolishError("ollama_unavailable"), 503, "ollama_unavailable"),
            (polisher.PolishError("model_missing"), 503, "model_missing"),
            (polisher.PolishError("ollama_timeout"), 504, "ollama_timeout"),
        ]
        for error, status, code in cases:
            with self.subTest(code=code), mock.patch.object(polisher, "_request", fake_ollama(reply=error)):
                r = self.client.post("/api/polish", json={"text": "hello"})
                self.assertEqual(r.status_code, status)
                self.assertEqual(r.get_json()["error"]["code"], code)
                self.assertNotIn("{model}", r.get_json()["error"]["message"])

    def test_thinking_only_model_is_refused_quickly(self):
        calls = []
        thinking = fake_ollama(template="{{ if $last }}<|im_start|>assistant\n<think>\n{{ end }}", calls=calls)
        with mock.patch.object(polisher, "_request", thinking):
            r = self.client.post("/api/polish", json={"text": "hello"})
        self.assertEqual(r.get_json()["error"]["code"], "model_thinks")
        self.assertEqual(calls, [])  # never sent to the model

    def test_requires_json_and_text(self):
        self.assertEqual(self.client.post("/api/polish", data="x", content_type="text/plain").status_code, 415)
        self.assertEqual(self.client.post("/api/polish", json={"text": 5}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
