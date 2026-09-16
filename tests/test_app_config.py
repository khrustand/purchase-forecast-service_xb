import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


class AppConfigTests(TestCase):
    def test_load_runtime_env_prefers_portable_file(self) -> None:
        from src.infrastructure.app_config import load_runtime_env

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            portable = root / ".env"
            appdata = root / "AppData" / "purchase-forecast-service" / ".env"
            appdata.parent.mkdir(parents=True)
            portable.write_text("APP_PORT=9001\n", encoding="utf-8")
            appdata.write_text("APP_PORT=9002\n", encoding="utf-8")

            with patch.dict(os.environ, {"APPDATA": str(root / "AppData")}, clear=True):
                loaded = load_runtime_env(root)

                self.assertEqual(loaded, portable)
                self.assertEqual(os.environ["APP_PORT"], "9001")

    def test_load_runtime_env_uses_appdata_when_portable_missing(self) -> None:
        from src.infrastructure.app_config import load_runtime_env

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            appdata = root / "AppData" / "purchase-forecast-service" / ".env"
            appdata.parent.mkdir(parents=True)
            appdata.write_text("APP_PORT=9002\n", encoding="utf-8")

            with patch.dict(os.environ, {"APPDATA": str(root / "AppData")}, clear=True):
                loaded = load_runtime_env(root)

                self.assertEqual(loaded, appdata)
                self.assertEqual(os.environ["APP_PORT"], "9002")

    def test_write_appdata_env_saves_known_values_without_unknown_keys(self) -> None:
        from src.infrastructure.app_config import write_appdata_env

        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"APPDATA": directory}, clear=True):
                path = write_appdata_env(
                    {
                        "SUPABASE_URL": "https://example.supabase.co",
                        "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_test",
                        "SUPABASE_STORAGE_BUCKET": "uploads",
                        "APP_PORT": "8000",
                        "UNKNOWN": "ignored",
                    }
                )

                saved = path.read_text(encoding="utf-8")

        self.assertIn("STORAGE_BACKEND=supabase", saved)
        self.assertIn("SUPABASE_URL=https://example.supabase.co", saved)
        self.assertIn("SUPABASE_SERVICE_ROLE_KEY=sb_secret_test", saved)
        self.assertIn("SUPABASE_STORAGE_BUCKET=uploads", saved)
        self.assertNotIn("UNKNOWN", saved)

    def test_has_database_config_requires_supabase_url_and_secret_key(self) -> None:
        from src.infrastructure.app_config import has_database_config

        with patch.dict(
            os.environ,
            {
                "STORAGE_BACKEND": "supabase",
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_test",
            },
            clear=True,
        ):
            self.assertTrue(has_database_config())

        with patch.dict(os.environ, {"STORAGE_BACKEND": "supabase", "SUPABASE_URL": "https://example.supabase.co"}, clear=True):
            self.assertFalse(has_database_config())
