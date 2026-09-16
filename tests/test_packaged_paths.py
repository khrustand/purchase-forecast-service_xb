import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


class PackagedPathsTests(TestCase):
    def test_project_path_uses_pyinstaller_temp_directory_when_frozen(self) -> None:
        from src.infrastructure.paths import project_path

        with tempfile.TemporaryDirectory() as directory:
            bundled = Path(directory)
            target = bundled / "data" / "examples" / "purchase_items.json"
            target.parent.mkdir(parents=True)
            target.write_text("[]", encoding="utf-8")

            with patch.object(sys, "frozen", True, create=True):
                with patch.object(sys, "_MEIPASS", str(bundled), create=True):
                    self.assertEqual(project_path("data/examples/purchase_items.json"), target)

    def test_project_path_falls_back_to_working_directory(self) -> None:
        from src.infrastructure.paths import project_path

        self.assertEqual(project_path("data/examples/purchase_items.json"), Path("data/examples/purchase_items.json"))
