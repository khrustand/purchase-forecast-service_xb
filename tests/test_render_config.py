from pathlib import Path
from unittest import TestCase


class RenderConfigTests(TestCase):
    def test_render_uses_python_runtime_without_docker(self) -> None:
        content = Path("render.yaml").read_text(encoding="utf-8")

        self.assertIn("runtime: python", content)
        self.assertIn("buildCommand: python -m unittest", content)
        self.assertIn("startCommand: python -m src.app.web_server", content)
        self.assertNotIn("runtime: docker", content)
        self.assertNotIn("dockerfilePath", content)
