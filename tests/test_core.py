import os
import tempfile
import unittest

DB_PATH = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_PATH"] = DB_PATH

import database
from filebee import is_filebee_url


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()

    def test_filebee_url_validation(self):
        self.assertTrue(is_filebee_url("https://filebee.live/"))
        self.assertTrue(is_filebee_url("https://new4.filebee.live/file/abc123"))
        self.assertFalse(is_filebee_url("http://filebee.live/file/abc"))
        self.assertFalse(is_filebee_url("https://evilfilebee.live/file/abc"))
        self.assertFalse(is_filebee_url("https://example.com/file/abc"))

    def test_user_and_link_storage(self):
        user_id = 876543210
        database.touch_user(user_id, "testuser", "Tester", 1700000000)
        row = database.get_user(user_id)
        self.assertEqual(row["folder_created"], 1700000000)
        database.add_file(user_id, "video.mp4", 4096,
                          "https://new4.filebee.live/file/xyz", 1700000001, "shared-link")
        recent = database.recent_files(user_id, 1)
        self.assertEqual(recent[0]["download_url"], "https://new4.filebee.live/file/xyz")
        self.assertEqual(recent[0]["file_size"], 4096)

    def test_bot_side_expiry(self):
        user_id = 876543210
        database.touch_user(user_id, "testuser", "Tester", 1700000000)
        database.set_record_expiry(user_id, 1700000100)
        self.assertEqual(database.get_user(user_id)["record_expire"], 1700000100)


if __name__ == "__main__":
    unittest.main()
