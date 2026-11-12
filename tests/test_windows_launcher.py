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
        edge_path = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

        result = open_windows_app_window(
            "http://localhost:8000",
            popen=lambda args: calls.append(list(args)) or process,
            fallback=lambda _url: None,
            edge_executable=lambda: edge_path,
        )
        self.assertIs(result, process)
        self.assertEqual(calls[0][0:3], [str(edge_path), "--app=http://localhost:8000", "--new-window"])
        self.assertIn("--no-first-run", calls[0])
        self.assertTrue(any(arg.startswith("--user-data-dir=") for arg in calls[0]))

    def test_open_windows_app_window_falls_back_to_browser(self) -> None:
        from src.app.windows_launcher import open_windows_app_window

        opened: list[str] = []

        self.assertIsNone(
            open_windows_app_window(
                "http://localhost:8000",
                popen=lambda _args: (_ for _ in ()).throw(FileNotFoundError()),
                fallback=opened.append,
                edge_executable=lambda: None,
            )
        )
        self.assertEqual(opened, ["http://localhost:8000"])

    def test_find_edge_executable_checks_standard_install_paths(self) -> None:
        from src.app.windows_launcher import find_edge_executable

        expected = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

        result = find_edge_executable(
            exists=lambda path: path == expected,
            command_lookup=lambda _name: None,
        )

        self.assertEqual(result, expected)

    def test_window_close_triggers_shutdown_callback(self) -> None:
        from src.app.windows_launcher import wait_for_window_close

        events: list[str] = []

        class FakeProcess:
            def wait(self) -> None:
                events.append("waited")

        times = iter([10, 12])
        wait_for_window_close(
            FakeProcess(),
            shutdown=lambda: events.append("shutdown"),
            monotonic=lambda: next(times),
            minimum_runtime_seconds=1,
        )

        self.assertEqual(events, ["waited", "shutdown"])

    def test_fast_edge_handoff_does_not_stop_server_immediately(self) -> None:
        from src.app.windows_launcher import wait_for_window_close

        events: list[str] = []

        class FakeProcess:
            def wait(self) -> None:
                events.append("waited")

        times = iter([10, 10.1])
        wait_for_window_close(
            FakeProcess(),
            shutdown=lambda: events.append("shutdown"),
            monotonic=lambda: next(times),
            minimum_runtime_seconds=1,
        )

        self.assertEqual(events, ["waited"])

    def test_main_keeps_server_open_when_edge_hands_off_immediately(self) -> None:
        from src.app import windows_launcher

        calls: list[object] = []

        class FakeServer:
            def shutdown(self) -> None:
                calls.append("shutdown")

            def server_close(self) -> None:
                calls.append("server_close")

        class FastExitProcess:
            def wait(self) -> None:
                calls.append("waited")

        times = iter([10, 10.1])

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
                    fake_time.monotonic = lambda: next(times)
                    with patch.object(windows_launcher, "create_app_server", lambda port: calls.append(("server", port)) or FakeServer()):
                        with patch.object(windows_launcher, "run_app_server", lambda _server: calls.append("serve")):
                            with patch.object(windows_launcher, "open_windows_app_window", lambda _url: FastExitProcess()):
                                with patch.object(windows_launcher, "keep_server_alive", lambda _thread: calls.append("join")):
                                    result = windows_launcher.main()

        self.assertEqual(result, 0)
        self.assertEqual(calls, [("server", 8000), "serve", "waited", "join"])
