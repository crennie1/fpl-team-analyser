"""Reload guard: app.py reloads every fpl module (and clears the caches) when the
fpl code or SQL files differ from what the loaded modules were imported under."""
import importlib
import os
import sys
import types
import uuid

import pytest

from app import code_signature, reload_if_code_changed


def _tree(tmp_path):
    pkg = tmp_path / "fpl"
    (pkg / "sql").mkdir(parents=True)
    (pkg / "ui").mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "suggest.py").write_text("x = 1\n")
    (pkg / "ui" / "kits.py").write_text("KITS = {}\n")
    (pkg / "sql" / "squad.sql").write_text("SELECT 1;\n")
    return pkg


def test_code_signature_is_stable_when_nothing_changes(tmp_path):
    _tree(tmp_path)
    assert code_signature(tmp_path) == code_signature(tmp_path)


def test_code_signature_changes_when_a_py_file_mtime_changes(tmp_path):
    pkg = _tree(tmp_path)
    before = code_signature(tmp_path)
    os.utime(pkg / "ui" / "kits.py", ns=(1, 1_000_000_000))
    assert code_signature(tmp_path) != before


def test_code_signature_changes_when_a_sql_file_changes(tmp_path):
    pkg = _tree(tmp_path)
    before = code_signature(tmp_path)
    (pkg / "sql" / "squad.sql").write_text("SELECT projected3 FROM x;\n")
    assert code_signature(tmp_path) != before


def test_code_signature_changes_when_a_file_is_added(tmp_path):
    pkg = _tree(tmp_path)
    before = code_signature(tmp_path)
    (pkg / "new.py").write_text("")
    assert code_signature(tmp_path) != before


def test_code_signature_ignores_pycache(tmp_path):
    pkg = _tree(tmp_path)
    before = code_signature(tmp_path)
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "suggest.py").write_text("junk\n")
    (pkg / "__pycache__" / "suggest.cpython-313.pyc").write_bytes(b"junk")
    assert code_signature(tmp_path) == before


def _mods():
    return {name: types.SimpleNamespace() for name in
            ("fpl", "fpl.suggest", "fpl.ui.kits", "fplx.thing", "json")}


def test_reload_without_recorded_signature_purges_every_fpl_module():
    mods, state = _mods(), types.SimpleNamespace()
    assert reload_if_code_changed("sig1", mods, state) == ["fpl", "fpl.suggest", "fpl.ui.kits"]
    assert sorted(mods) == ["fplx.thing", "json"]
    assert state._fpl_code_signature == "sig1"


def test_reload_with_same_signature_keeps_everything():
    mods, state = _mods(), types.SimpleNamespace(_fpl_code_signature="sig1")
    before = dict(mods)
    assert reload_if_code_changed("sig1", mods, state) == []
    assert mods == before
    assert state._fpl_code_signature == "sig1"


def test_reload_with_different_signature_purges_and_records():
    mods, state = _mods(), types.SimpleNamespace(_fpl_code_signature="old")
    assert reload_if_code_changed("new", mods, state) == ["fpl", "fpl.suggest", "fpl.ui.kits"]
    assert sorted(mods) == ["fplx.thing", "json"]
    assert state._fpl_code_signature == "new"


def test_reload_with_nothing_loaded_records_the_signature():
    mods, state = {"json": types.SimpleNamespace()}, types.SimpleNamespace()
    assert reload_if_code_changed("sig1", mods, state) == []
    assert state._fpl_code_signature == "sig1"


def test_failed_import_during_a_push_heals_on_the_next_run(tmp_path):
    """A run that purges, then imports half-updated files, fails; the next run reloads."""
    prefix = "fplreload_" + uuid.uuid4().hex[:8]
    pkg = tmp_path / prefix
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "b.py").write_text("OLD = 1\n")
    (pkg / "a.py").write_text(f"from {prefix}.b import OLD\n")
    state = types.SimpleNamespace()

    def run():
        """What app.py does each run: fingerprint, purge if needed, import, record."""
        sig = code_signature(tmp_path, prefix)
        reload_if_code_changed(sig, sys.modules, state, prefix)
        try:
            importlib.invalidate_caches()
            return importlib.import_module(f"{prefix}.a")
        finally:
            state._fpl_code_signature = sig

    sys.path.insert(0, str(tmp_path))
    try:
        assert run().OLD == 1                                   # v1 loaded and recorded
        (pkg / "a.py").write_text(f"from {prefix}.b import OLD, NEW_NAME\n")   # v2 a only
        with pytest.raises(ImportError):
            run()
        (pkg / "b.py").write_text("OLD = 1\nNEW_NAME = 'v2'\n")               # v2 b lands
        a = run()
        assert a.NEW_NAME == "v2"
        assert sys.modules[f"{prefix}.b"].NEW_NAME == "v2"
    finally:
        sys.path.remove(str(tmp_path))
        for name in [n for n in sys.modules if n == prefix or n.startswith(prefix + ".")]:
            del sys.modules[name]
