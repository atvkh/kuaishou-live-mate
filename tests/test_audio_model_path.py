import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


fake_funasr_onnx = types.ModuleType("funasr_onnx")
fake_funasr_onnx.SenseVoiceSmall = object
with mock.patch.dict(sys.modules, {"funasr_onnx": fake_funasr_onnx}):
    from src.audio import _get_model_dir


class ModelPathTest(unittest.TestCase):
    def test_finds_model_in_pyinstaller_bundle_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_dir = Path(temp_dir) / "_internal"
            model_dir = bundle_dir / "models" / "sensevoice"
            model_dir.mkdir(parents=True)
            (model_dir / "model.onnx").write_bytes(b"onnx")

            executable = Path(temp_dir) / "旁白.exe"
            with (
                mock.patch.dict(
                    os.environ,
                    {"HOME": temp_dir, "USERPROFILE": temp_dir},
                ),
                mock.patch.object(sys, "_MEIPASS", str(bundle_dir), create=True),
                mock.patch.object(sys, "argv", [str(executable)]),
            ):
                self.assertEqual(_get_model_dir(), str(model_dir))


if __name__ == "__main__":
    unittest.main()
