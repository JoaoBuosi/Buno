import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("buno_launcher", ROOT / "buno.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def test_configuration_is_created_once_and_preserves_existing_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            api = Path(folder)
            (api / ".env.example").write_text("DATABASE_URL=local-example\nJWT_SECRET=substitua-por-um-segredo-aleatorio\n", encoding="utf-8")
            self.assertTrue(launcher.create_local_config(api))
            first = (api / ".env").read_bytes()
            self.assertNotIn(b"substitua-por", first)
            self.assertIn(b"DATABASE_URL=local-example", first)
            self.assertFalse(launcher.create_local_config(api))
            self.assertEqual((api / ".env").read_bytes(), first)

    def test_existing_user_configuration_is_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            api = Path(folder)
            original = b"USER_CONFIGURATION=preserve-exactly\r\n"
            (api / ".env").write_bytes(original)
            self.assertFalse(launcher.create_local_config(api))
            self.assertEqual((api / ".env").read_bytes(), original)

    def test_busy_port_has_a_clear_error(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); sock.listen()
            with self.assertRaisesRegex(launcher.SetupError, "porta"):
                launcher.check_ports((sock.getsockname()[1],))

    @unittest.skipIf(os.name == "nt", "Process-group integration tested on Linux only")
    def test_shutdown_stops_only_spawned_processes(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
        try:
            launcher.stop_processes([child])
            self.assertIsNotNone(child.poll())
        finally:
            if child.poll() is None:
                child.kill(); child.wait()


if __name__ == "__main__":
    unittest.main()
