import io
import os
import tempfile
import unittest

import fitz

import app as anveshak


class AnveshakSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_base = anveshak.BASE
        anveshak.BASE = self.temp_dir.name
        anveshak.app.config.update(TESTING=True)
        self.client = anveshak.app.test_client()

    def tearDown(self):
        anveshak.BASE = self.original_base
        self.temp_dir.cleanup()

    def test_home_page_renders(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Anveshak", response.data)

    def test_pdf_upload_and_native_text_search(self):
        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_text((72, 72), "hello anveshak")
        payload = pdf.tobytes()
        pdf.close()

        response = self.client.post(
            "/upload",
            data={"file": (io.BytesIO(payload), "sample.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        result = response.get_json()
        self.assertEqual(result["total_pages"], 1)
        session_id = result["session"]

        search_response = self.client.post(
            "/search",
            json={"session": session_id, "search_term": "hello"},
        )
        self.assertEqual(search_response.status_code, 200)
        search_result = search_response.get_json()
        self.assertGreaterEqual(search_result["stats"]["total_matches"], 1)


if __name__ == "__main__":
    unittest.main()
