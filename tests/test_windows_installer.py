from pathlib import Path
from unittest import TestCase


class WindowsInstallerTests(TestCase):
    def test_inno_setup_script_installs_app_without_secrets(self) -> None:
        script = Path("installer/purchase-forecast-service.iss")

        content = script.read_text(encoding="utf-8")

        self.assertIn('#define MyAppName "Сервис заказов кулинарии"', content)
        self.assertIn("AppName={#MyAppName}", content)
        self.assertIn("DefaultDirName={localappdata}\\PurchaseForecastService", content)
        self.assertIn("OutputBaseFilename=PurchaseForecastServiceSetup", content)
        self.assertIn('Source: "..\\dist\\purchase-forecast-service.exe"', content)
        self.assertIn('Source: "..\\dist\\.env.example"', content)
        self.assertIn("Icons", content)
        self.assertIn("Run", content)
        self.assertNotIn("SUPABASE_SERVICE_ROLE_KEY=", content)
        self.assertNotIn("sb_secret_", content)

    def test_installer_build_script_compiles_inno_setup(self) -> None:
        script = Path("scripts/build_installer.ps1")

        content = script.read_text(encoding="utf-8")

        self.assertIn("scripts\\build_windows.ps1", content)
        self.assertIn("ISCC.exe", content)
        self.assertIn("installer\\purchase-forecast-service.iss", content)
        self.assertIn("PurchaseForecastServiceSetup.exe", content)
