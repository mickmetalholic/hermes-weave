"""Offline installer smoke tests using a fake Python package installer and isolated HOME."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        (self.home / ".hermes").mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        # The mocked Python delegates version checks to real Python, but substitutes venv/pip.
        python = self.bin / "python3"
        python.write_text(f'''#!/usr/bin/env bash
if [[ "$1" == '-m' && "$2" == 'venv' ]]; then
  mkdir -p "$3/bin"
  cp "$MOCK_VENV_PY" "$3/bin/python"
  chmod +x "$3/bin/python"
  exit 0
fi
exec "{sys.executable}" "$@"
''')
        python.chmod(0o755)
        mock_venv = self.root / "mock_venv_py"
        mock_venv.write_text('''#!/usr/bin/env bash
if [[ "$1" == '-m' && "$2" == 'pip' ]]; then
  [[ "$*" == *"git+https://github.com/mickmetalholic/hermes-weave.git@"* ]] || exit 65
  cat > "$(dirname "$0")/weave" <<'EOF'
#!/usr/bin/env bash
case "$1 $2" in
  'skill install') mkdir -p "$HOME/.hermes/skills/hermes-weave"; printf 'installed\\n' > "$HOME/.hermes/skills/hermes-weave/SKILL.md" ;;
  'doctor --json') printf '{"ok":true}\\n' ;;
  'init ') printf 'init\\n' ;;
  *) exit 99 ;;
esac
EOF
  chmod +x "$(dirname "$0")/weave"
  exit 0
fi
exit 77
''')
        mock_venv.chmod(0o755)
        # gh is deliberately broken: public-source installation must not call it.
        gh = self.bin / "gh"
        gh.write_text('#!/usr/bin/env bash\nexit 97\n')
        gh.chmod(0o755)
        self.env = {**os.environ,
                    "HOME": str(self.home),
                    "PATH": f"{self.bin}:{os.environ.get('PATH','')}",
                    "MOCK_VENV_PY": str(mock_venv)}

    def run_script(self, *flags: str, ok=True):
        result = subprocess.run(["bash", str(INSTALLER), *flags], env=self.env, text=True, capture_output=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_install_without_login_or_source_clone_and_rerun(self):
        self.run_script("--no-init")
        home = self.home / ".hermes-weave"
        self.assertTrue((home / "venv" / "bin" / "weave").is_file())
        self.assertTrue((self.home / ".hermes" / "skills" / "hermes-weave" / "SKILL.md").is_file())
        self.assertFalse((home / "source").exists())
        self.assertEqual((self.home / ".local" / "bin" / "weave").resolve(), (home / "venv" / "bin" / "weave"))
        self.run_script("--no-init")

    def test_refuses_existing_non_weave_binary(self):
        executable = self.home / ".local" / "bin" / "weave"
        executable.parent.mkdir(parents=True)
        executable.write_text("keep existing executable\n")
        result = self.run_script("--no-init", ok=False)
        self.assertIn("not ours", result.stderr)
        self.assertEqual(executable.read_text(), "keep existing executable\n")
        self.assertFalse((self.home / ".hermes-weave" / "venv").exists())

    def test_rejects_suspicious_ref(self):
        result = self.run_script("--ref", "--upload-token", ok=False)
        self.assertIn("Invalid Git ref", result.stderr)
        self.assertFalse((self.home / ".hermes-weave").exists())

    def test_missing_hermes_home_blocks_install(self):
        shutil.rmtree(self.home / ".hermes")
        result = self.run_script(ok=False)
        self.assertIn("Hermes home", result.stderr)


if __name__ == "__main__":
    unittest.main()
