import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


class SetupPageTests(TestCase):
    def test_setup_page_is_russian_and_does_not_echo_secret(self) -> None:
        from src.app.web_server import render_setup_html

        html = render_setup_html(error="Проверьте ключ", values={"SUPABASE_SERVICE_ROLE_KEY": "sb_secret_test"})

        self.assertIn("Первичная настройка", html)
        self.assertIn("Проверьте ключ", html)
        self.assertIn("URL проекта Supabase", html)
        self.assertNotIn("sb_secret_test", html)

    def test_save_setup_config_writes_appdata_env_and_reloads_storage(self) -> None:
        import src.app.web_server as web_server

        with tempfile.TemporaryDirectory() as directory:
            appdata = Path(directory) / "AppData"
            with patch.dict(os.environ, {"APPDATA": str(appdata)}, clear=True):
                with patch.object(web_server, "reload_report_storage") as reload_storage:
                    saved = web_server.save_setup_config(
                        {
                            "SUPABASE_URL": "https://example.supabase.co",
                            "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_test",
                            "SUPABASE_STORAGE_BUCKET": "",
                            "APP_USERNAME": "manager",
                            "APP_PASSWORD": "secret",
                        }
                    )

                content = saved.read_text(encoding="utf-8")

        self.assertIn("STORAGE_BACKEND=supabase", content)
        self.assertIn("SUPABASE_STORAGE_BUCKET=uploads", content)
        self.assertIn("APP_USERNAME=manager", content)
        self.assertIn("APP_PASSWORD=secret", content)
        reload_storage.assert_called_once()

    def test_save_setup_config_rejects_missing_required_fields(self) -> None:
        from src.app.web_server import save_setup_config
        from src.infrastructure.app_config import AppConfigError

        with self.assertRaises(AppConfigError):
            save_setup_config({"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""})
