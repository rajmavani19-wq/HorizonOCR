import importlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path


class ProductionSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data_dir = tempfile.TemporaryDirectory()
        os.environ["APP_ENV"] = "development"
        os.environ["DATA_DIR"] = cls.data_dir.name
        os.environ["MAX_DOCUMENT_PAGES"] = "2"
        sys.modules.pop("server", None)
        cls.server = importlib.import_module("server")
        cls.server.app.config.update(TESTING=True)

    @classmethod
    def tearDownClass(cls):
        cls.data_dir.cleanup()

    def setUp(self):
        self.client = self.server.app.test_client()

    def csrf(self, client=None):
        response = (client or self.client).get("/api/csrf")
        self.assertEqual(response.status_code, 200)
        return response.get_json()["csrf_token"]

    def register(self, username, email, password="correct-horse-battery-staple"):
        token = self.csrf()
        response = self.client.post(
            "/api/register",
            json={"username": username, "email": email, "password": password},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 201)
        return response.get_json()["user"]

    def test_mutating_requests_require_csrf(self):
        response = self.client.post(
            "/api/register",
            json={"username": "no_csrf", "email": "no_csrf@example.test", "password": "correct-horse-battery-staple"},
        )
        self.assertEqual(response.status_code, 403)

    def test_registration_returns_authenticated_csrf_session(self):
        self.register("owner", "owner@example.test")
        response = self.client.get("/api/me")
        payload = response.get_json()
        self.assertTrue(payload["authenticated"])
        self.assertIn("csrf_token", payload)

    def test_unauthenticated_history_is_rejected(self):
        response = self.client.get("/api/history")
        self.assertEqual(response.status_code, 401)

    def test_cross_account_images_are_not_exposed(self):
        owner = self.register("image_owner", "image_owner@example.test")
        with self.server.get_db() as conn:
            conn.execute(
                "INSERT INTO document_images (user_id, doc_hash, img_name, mime_type, img_data) VALUES (?, ?, ?, ?, ?)",
                (owner["id"], "fixture", "fixture.png", "image/png", b"fixture-bytes"),
            )

        other_client = self.server.app.test_client()
        other_token = self.csrf(other_client)
        response = other_client.post(
            "/api/register",
            json={"username": "other_user", "email": "other@example.test", "password": "correct-horse-battery-staple"},
            headers={"X-CSRF-Token": other_token},
        )
        self.assertEqual(response.status_code, 201)
        response = other_client.get("/api/images/fixture.png")
        self.assertEqual(response.status_code, 404)

    def test_upload_rejects_unsupported_extensions(self):
        self.register("uploader", "uploader@example.test")
        token = self.csrf()
        response = self.client.post(
            "/api/ocr",
            data={"mode": "base", "file": (io.BytesIO(b"not-a-document"), "payload.exe")}, 
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 415)

    def test_health_response_has_protective_headers(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")


if __name__ == "__main__":
    unittest.main()
