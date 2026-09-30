import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


class WindowsLauncherTests(TestCase):
    def test_load_env_file_sets_missing_values(self) -> None:
        from src.app.windows_launcher import load_env_file

        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "APP_PORT=9000\nAPP_USERNAME=manager\n# comment\nEMPTY=\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"APP_USERNAME": "existing"}, clear=True):
                load_env_file(env_path)

                self.assertEqual(os.environ["APP_PORT"], "9000")
                self.assertEqual(os.environ["APP_USERNAME"], "existing")
                self.assertEqual(os.environ["EMPTY"], "")

    def test_main_sets_default_port_and_starts_server(self) -> None:
        from src.app import windows_launcher

        calls: list[object] = []

        class FakeServer:
            def shutdown(self) -> None:
                calls.append("shutdown")

            def server_close(self) -> None:
                calls.append("server_close")

        with patch.dict(
            os.environ,
            {
                "STORAGE_BACKEND": "supabase",
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_test",
            },
            clear=True,
        ):
            with patch.object(windows_launcher, "load_runtime_env", lambda *_args: None):
                with patch.object(windows_launcher, "time") as fake_time:
                    fake_time.sleep = lambda _seconds: None
                    with patch.object(windows_launcher, "create_app_server", lambda port: calls.append(("server", port)) or FakeServer()):
                        with patch.object(windows_launcher, "run_app_server", lambda server: calls.append("serve")):
                            with patch.object(windows_launcher, "open_windows_app_window", lambda url: calls.append(url) or None):
                                result = windows_launcher.main()
                                self.assertEqual(os.environ["APP_PORT"], "8000")

        self.assertEqual(result, 0)
        self.assertEqual(calls, [("server", 8000), "serve", "http://localhost:8000", "shutdown", "server_close"])

    def test_main_opens_setup_when_database_config_is_missing(self) -> None:
        from src.app import windows_launcher

        calls: list[object] = []

        class FakeServer:
            def shutdown(self) -> None:
                calls.append("shutdown")

            def server_close(self) -> None:
                calls.append("server_close")

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(windows_launcher, "load_runtime_env", lambda *_args: None):
                with patch.object(windows_launcher, "time") as fake_time:
                    fake_time.sleep = lambda _seconds: None
                    with patch.object(windows_launcher, "create_app_server", lambda port: calls.append(("server", port)) or FakeServer()):
                        with patch.object(windows_launcher, "run_app_server", lambda server: calls.append("serve")):
                            with patch.object(windows_launcher, "open_windows_app_window", lambda url: calls.append(url) or None):
                                result = windows_launcher.main()
                                self.assertEqual(os.environ["APP_PORT"], "8000")

        self.assertEqual(result, 0)
        self.assertEqual(calls, [("server", 8000), "serve", "http://localhost:8000/setup", "shutdown", "server_close"])

    def test_open_app_window_later_uses_given_url(self) -> None:
        from src.app.windows_launcher import open_app_window_later

        opened: list[str] = []
        thread = open_app_window_later("http://localhost:9000", delay_seconds=0, opener=opened.append)
        thread.join(timeout=2)

        self.assertEqual(opened, ["http://localhost:9000"])

    def test_open_windows_app_window_uses_edge_app_mode(self) -> None:
        from src.app.windows_launcher import open_windows_app_window

        calls: list[list[str]] = []
        process = object()

        result = open_windows_app_window(
            "http://localhost:8000",
            popen=lambda args: calls.append(list(args)) or process,
            fallback=lambda _url: None,
        )
        self.assertIs(result, process)
        self.assertEqual(calls, [["msedge", "--app=http://localhost:8000", "--new-window"]])

    def test_open_windows_app_window_falls_back_to_browser(self) -> None:
        from src.app.windows_launcher import open_windows_app_window

        opened: list[str] = []

        self.assertIsNone(
            open_windows_app_window(
                "http://localhost:8000",
                popen=lambda _args: (_ for _ in ()).throw(FileNotFoundError()),
                fallback=opened.append,
            )
        )
        self.assertEqual(opened, ["http://localhost:8000"])

    def test_window_close_triggers_shutdown_callback(self) -> None:
        from src.app.windows_launcher import wait_for_window_close

        events: list[str] = []

        class FakeProcess:
            def wait(self) -> None:
                events.append("waited")

        wait_for_window_close(FakeProcess(), shutdown=lambda: events.append("shutdown"))

        self.assertEqual(events, ["waited", "shutdown"])
