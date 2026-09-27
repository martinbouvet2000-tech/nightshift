import os
import sys
from pathlib import Path

import pytest

from nightshift.cli import DEMO_OUT, demo_out


def test_uses_the_requested_folder_when_writable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out, fell_back = demo_out(DEMO_OUT, explicit=False)
    assert out == (tmp_path / DEMO_OUT).resolve()
    assert fell_back is False
    assert out.is_dir()


def test_leaves_no_probe_file_behind(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out, _ = demo_out(DEMO_OUT, explicit=False)
    assert list(out.iterdir()) == []


def test_an_explicit_path_is_honoured(tmp_path):
    target = tmp_path / "somewhere" / "else"
    out, fell_back = demo_out(str(target), explicit=True)
    assert out == target.resolve()
    assert fell_back is False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
class TestReadOnlyWorkingDirectory:
    @pytest.fixture
    def locked(self, tmp_path, monkeypatch):
        d = tmp_path / "locked"
        d.mkdir()
        monkeypatch.chdir(d)
        os.chmod(d, 0o500)          # r-x: no new folder can be created here
        yield d
        os.chmod(d, 0o700)

    def test_falls_back_to_a_temp_folder(self, locked):
        out, fell_back = demo_out(DEMO_OUT, explicit=False)
        assert fell_back is True
        assert out.is_dir()
        assert locked not in out.parents

    def test_an_explicit_path_raises_instead_of_moving(self, locked):
        # Silently writing somewhere else than asked would be worse than failing.
        with pytest.raises(OSError):
            demo_out(str(locked / "mine"), explicit=True)


def test_user_home_is_expanded(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    out, _ = demo_out("~/demo-here", explicit=True)
    assert out == (tmp_path / "demo-here").resolve()
    assert Path(out).is_dir()
