"""HTTP API and page tests using Flask's test client with a temporary database."""
import shutil
import tempfile
import unittest

from correcty import create_app

NEW_TEMPLATE = {
    "title": "Mock Exam Confirmation",
    "description": "Date and time of the mock exam",
    "body": "Hi {{student_name}}, your mock exam is on {{date}}.",
    "closing": "Good luck, {{student_name}}!",
    "pinned": False,
    "sections": [{
        "id": "s1", "question": "Online or in person?",
        "choices": [
            {"id": "c1", "label": "Online", "text": "Join here: {{link}}"},
            {"id": "c2", "label": "In person", "text": "Please arrive 15 minutes early."},
        ],
    }],
    "variables": [{"name": "date", "label": "Exam date", "type": "text", "required": True, "placeholder": "Sat 12 Oct"}],
}


class ApiTestCase(unittest.TestCase):
    seed = False

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = create_app({"DATA_DIR": self.tmp, "SEED_EXAMPLES": self.seed, "TESTING": True})
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def create(self, **overrides):
        response = self.client.post("/api/templates", json={**NEW_TEMPLATE, **overrides})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["template"]


class CrudTests(ApiTestCase):
    def test_create_get_list(self):
        tpl = self.create()
        self.assertEqual(tpl["title"], "Mock Exam Confirmation")
        self.assertEqual([v["name"] for v in tpl["variables"]], ["student_name", "date", "link"])
        self.assertTrue(tpl["created_at"] and tpl["updated_at"])

        data = self.client.get(f"/api/templates/{tpl['id']}").get_json()
        self.assertEqual(data["template"]["body"], NEW_TEMPLATE["body"])
        self.assertEqual(data["form"]["fields"]["date"]["label"], "Exam date")
        self.assertEqual(data["form"]["fields"]["student_name"]["label"], "Student name")

        listing = self.client.get("/api/templates").get_json()["templates"]
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]["inputs"], 3)
        self.assertEqual(listing[0]["sections"], 1)

    def test_persists_across_app_restarts(self):
        tpl = self.create()
        restarted = create_app({"DATA_DIR": self.tmp, "SEED_EXAMPLES": False}).test_client()
        self.assertEqual(restarted.get(f"/api/templates/{tpl['id']}").status_code, 200)

    def test_update(self):
        tpl = self.create()
        payload = {**NEW_TEMPLATE, "title": "Renamed", "body": "Only {{x}}", "sections": [], "closing": ""}
        response = self.client.put(f"/api/templates/{tpl['id']}", json=payload)
        self.assertEqual(response.status_code, 200)
        updated = self.client.get(f"/api/templates/{tpl['id']}").get_json()["template"]
        self.assertEqual(updated["title"], "Renamed")
        self.assertEqual([v["name"] for v in updated["variables"]], ["x"])
        self.assertEqual(updated["created_at"], tpl["created_at"])

    def test_update_validation_keeps_old_data(self):
        tpl = self.create()
        response = self.client.put(f"/api/templates/{tpl['id']}", json={**NEW_TEMPLATE, "title": ""})
        self.assertEqual(response.status_code, 422)
        fields = response.get_json()["error"]["fields"]
        self.assertEqual(fields[0]["field"], "title")
        self.assertTrue(fields[0]["message"])
        self.assertEqual(self.client.get(f"/api/templates/{tpl['id']}").get_json()["template"]["title"], tpl["title"])

    def test_pin_and_unpin(self):
        tpl = self.create()
        self.assertEqual(self.client.patch(f"/api/templates/{tpl['id']}/pin", json={"pinned": True}).status_code, 200)
        pinned = self.client.get("/api/templates?pinned=1").get_json()["templates"]
        self.assertEqual([t["id"] for t in pinned], [tpl["id"]])
        self.client.patch(f"/api/templates/{tpl['id']}/pin", json={"pinned": False})
        self.assertEqual(self.client.get("/api/templates?pinned=1").get_json()["templates"], [])
        self.assertEqual(self.client.patch(f"/api/templates/{tpl['id']}/pin", json={"pinned": "yes"}).status_code, 400)

    def test_delete(self):
        tpl = self.create()
        self.assertEqual(self.client.delete(f"/api/templates/{tpl['id']}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/templates/{tpl['id']}").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/templates/{tpl['id']}").status_code, 404)

    def test_search(self):
        self.create()
        self.create(title="Panel Login", body="Log in at panel.example.com", sections=[], closing="")
        titles = lambda q: [t["title"] for t in self.client.get(f"/api/templates?q={q}").get_json()["templates"]]
        self.assertEqual(titles("panel"), ["Panel Login"])
        self.assertEqual(titles("ARRIVE 15"), ["Mock Exam Confirmation"])  # text inside an optional answer
        self.assertEqual(titles("nothing-here"), [])

    def test_persian_search_ignores_letter_variants(self):
        self.create(title="یادآوری کلاس", body="سلام {{name}}", sections=[], closing="")
        found = self.client.get("/api/templates?q=يادآوري").get_json()["templates"]  # Arabic ي
        self.assertEqual(len(found), 1)


class RenderApiTests(ApiTestCase):
    def test_render_flow(self):
        tpl = self.create()
        url = f"/api/templates/{tpl['id']}/render"
        r = self.client.post(url, json={"choices": {}, "values": {"student_name": "Ali"}}).get_json()
        self.assertFalse(r["ok"])
        self.assertEqual({e["field"] for e in r["errors"]}, {"var:date"})
        self.assertTrue(all(e["message"] for e in r["errors"]))

        r = self.client.post(url, json={"choices": {"s1": "c2"}, "values": {"student_name": "Ali", "date": "Sat"}}).get_json()
        self.assertTrue(r["ok"])
        self.assertEqual(
            r["text"],
            "Hi Ali, your mock exam is on Sat.\nPlease arrive 15 minutes early.\nGood luck, Ali!",
        )

        r = self.client.post(url, json={"choices": {"s1": "c1"}, "values": {"student_name": "Ali", "date": "Sat"}}).get_json()
        self.assertEqual([e["field"] for e in r["errors"]], ["var:link"])

    def test_render_missing_template(self):
        self.assertEqual(self.client.post("/api/templates/999/render", json={}).status_code, 404)

    def test_preview_validates_draft(self):
        r = self.client.post("/api/preview", json={"template": {"title": "", "body": "{{x"}})
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/preview", json={"template": NEW_TEMPLATE, "choices": {"s1": "c2"},
                                                   "values": {"student_name": "A", "date": "B"}})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["result"]["ok"])

    def test_localized_errors(self):
        tpl = self.create()
        self.client.set_cookie("correcty_lang", "fa")
        r = self.client.post(f"/api/templates/{tpl['id']}/render", json={"choices": {"s1": "c2"}, "values": {}}).get_json()
        self.assertIn("پر کن", r["errors"][0]["message"])


class SafetyTests(ApiTestCase):
    def test_writes_require_json(self):
        r = self.client.post("/api/templates", data='{"title": "x", "body": "y"}', content_type="text/plain")
        self.assertEqual(r.status_code, 415)

    def test_malformed_json(self):
        r = self.client.post("/api/templates", data="{not json", content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_cross_origin_writes_are_blocked(self):
        tpl = self.create()
        r = self.client.delete(f"/api/templates/{tpl['id']}", headers={"Origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)
        r = self.client.post("/api/templates", json=NEW_TEMPLATE, headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status_code, 403)
        r = self.client.post("/api/templates", json=NEW_TEMPLATE, headers={"Origin": "http://localhost"})
        self.assertEqual(r.status_code, 201)

    def test_foreign_host_header_is_blocked(self):
        self.assertEqual(self.client.get("/", headers={"Host": "attacker.example"}).status_code, 403)

    def test_security_headers(self):
        r = self.client.get("/")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")

    def test_html_is_escaped(self):
        tpl = self.create(title="<script>alert(1)</script>", pinned=True)
        page = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertEqual(self.client.get(f"/api/templates/{tpl['id']}").get_json()["template"]["title"], "<script>alert(1)</script>")

    def test_static_files_use_versioned_urls_and_revalidate(self):
        import re
        page = self.client.get("/").get_data(as_text=True)
        css = re.search(r'href="(/static/[0-9a-f]{10}/css/styles\.css)"', page)
        script = re.search(r'src="(/static/[0-9a-f]{10}/js/quick-reply\.js)"', page)
        self.assertTrue(css and script, "static URLs should carry a version folder")
        module = script.group(1).replace("quick-reply.js", "generator.js")  # how relative imports resolve
        r = self.client.get(module)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Cache-Control"], "no-cache")
        self.assertIn("javascript", r.headers["Content-Type"])
        r.close()

    def test_empty_states_render(self):
        home = self.client.get("/").get_data(as_text=True)
        self.assertIn("No pinned replies yet", home)
        manage = self.client.get("/templates").get_data(as_text=True)
        self.assertIn('id="tpl-empty"', manage)
        self.assertNotIn('id="tpl-empty" hidden', manage)

    def test_unknown_api_route_is_json(self):
        r = self.client.get("/api/nope")
        self.assertEqual(r.status_code, 404)
        self.assertIn("error", r.get_json())


class PageTests(ApiTestCase):
    seed = True

    def test_seeded_examples(self):
        titles = [t["title"] for t in self.client.get("/api/templates").get_json()["templates"]]
        self.assertIn("Panel Login", titles)

    def test_pages_render(self):
        for path in ["/", "/templates", "/templates/new", "/templates/1/edit"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.get("/templates/999/edit").status_code, 404)

    def test_language_switch(self):
        r = self.client.get("/lang/fa?next=/templates")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["Location"], "/templates")
        page = self.client.get("/templates").get_data(as_text=True)
        self.assertIn('dir="rtl"', page)
        self.assertIn("مدیریت قالب‌ها", page)

    def test_language_switch_rejects_external_redirects(self):
        for target in ["https://evil.example", "//evil.example", "/\\evil.example"]:
            with self.subTest(target=target):
                self.assertEqual(self.client.get(f"/lang/en?next={target}").headers["Location"], "/")

    def test_panel_login_seed(self):
        url = "/api/templates/1/render"
        main = "لطفا از طریق لینک panel.example.com وارد پنل خود بشید."
        # Not answered: only the main message, and nothing else is required.
        r = self.client.post(url, json={"choices": {}, "values": {}}).get_json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["text"], main)
        # "Has a number": the paragraph goes on the next line once the number is filled in.
        r = self.client.post(url, json={"choices": {"s1": "c1"}, "values": {}}).get_json()
        self.assertEqual([e["field"] for e in r["errors"]], ["var:number"])
        r = self.client.post(url, json={"choices": {"s1": "c1"}, "values": {"number": "09129876543"}}).get_json()
        self.assertEqual(r["text"], main + "\nو از شماره همراه 09129876543 جهت ورود استفاده کنید.")
        r = self.client.post(url, json={"choices": {"s1": "c2"}, "values": {}}).get_json()
        self.assertEqual(r["text"], main)

    def test_healthz(self):
        self.assertEqual(self.client.get("/healthz").get_json()["app"], "correcty")


if __name__ == "__main__":
    unittest.main()
