"""Atomic writers tolerate brief reader contention and fail closed otherwise."""
import importlib
import time

import pytest

import paths


@pytest.fixture(params=['settings', 'profile'])
def writer(request, tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    module = importlib.import_module(request.param)
    if request.param == 'settings':
        target = paths.settings_path()
        write = lambda: module.update({'llm': {'model': 'updated'}})
    else:
        target = paths.profile_path()
        write = lambda: module._atomic_write(target, '{"value":"updated"}')
    target.write_text('{"original":true}', encoding='utf-8')
    return module, target, write


def test_transient_permission_error_retries_same_closed_temporary(writer, monkeypatch):
    module, target, write = writer
    before = target.read_bytes()
    replace = module.os.replace
    attempts, delays = [], []

    def contested(source, destination):
        attempts.append((source, destination))
        if len(attempts) <= 2:
            assert target.read_bytes() == before
            raise PermissionError('reader still open')
        replace(source, destination)

    monkeypatch.setattr(module.os, 'replace', contested)
    monkeypatch.setattr(time, 'sleep', delays.append)
    write()
    assert len(attempts) == 3 and len(set(attempts)) == 1
    assert delays == pytest.approx([0.05, 0.1])
    assert b'updated' in target.read_bytes()
    assert list(target.parent.iterdir()) == [target]


def test_persistent_permission_error_is_bounded_preserves_original_and_cleans_temp(writer, monkeypatch):
    module, target, write = writer
    before = target.read_bytes()
    attempts, delays = [], []
    denied = PermissionError('persistent reader or access denial')

    def contested(source, destination):
        attempts.append((source, destination))
        raise denied

    monkeypatch.setattr(module.os, 'replace', contested)
    monkeypatch.setattr(time, 'sleep', delays.append)
    with pytest.raises(PermissionError) as exc:
        write()
    assert exc.value is denied
    assert len(attempts) == 5 and len(set(attempts)) == 1
    assert delays == pytest.approx([0.05, 0.1, 0.15, 0.2])
    assert target.read_bytes() == before
    assert list(target.parent.iterdir()) == [target]
