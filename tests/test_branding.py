"""Guard the public branding and separation from other installed applications."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from correcty import create_app, default_data_dir


class BrandingTests(unittest.TestCase):
    def test_fresh_install_has_generic_content_in_both_languages(self):
        with tempfile.TemporaryDirectory() as folder:
            client = create_app({"DATA_DIR": folder}).test_client()
            for language in ("en", "fa"):
                client.set_cookie("correcty_lang", language)
                for path in ("/", "/templates", "/templates/new", "/settings",
                             "/api/templates", "/api/prompts"):
                    with self.subTest(language=language, path=path):
                        response = client.get(path)
                        self.assertEqual(response.status_code, 200)
                        text = response.get_data(as_text=True)
                        for removed in ("IELTS", "ieltsdaily", "آیلتس", "ID Correct", "i-logo", "brand__mark"):
                            self.assertNotIn(removed, text)
                        if not path.startswith("/api/"):
                            self.assertIn("Correcty", text)

    def test_own_default_data_folder(self):
        with patch.dict(os.environ, {"APPDATA": "test-appdata", "XDG_DATA_HOME": "test-data"}, clear=True):
            self.assertIn(default_data_dir().name, ("Correcty", "correcty"))

    def test_own_data_override(self):
        with patch.dict(os.environ, {"CORRECTY_DATA_DIR": "correcty-test-data"}):
            self.assertEqual(default_data_dir(), Path("correcty-test-data"))
