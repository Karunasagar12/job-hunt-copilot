"""Fixed scheduler behavior without launching provider processes."""
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import paths
import settings


def module():
    return importlib.import_module('scheduler')


def utc(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


SCHEDULE = {'inbox_scan': '07:00', 'job_sourcing': '04:30', 'gmail_sent_poll_minutes': 15}


def job(name):
    return next(j for j in module().JOBS if j['id'] == name)


def test_interval_boundary_and_first_run():
    s = module()
    last = {'gmail_sent_poll': utc('2027-01-01T10:00').isoformat()}
    assert s.due_jobs(utc('2027-01-01T10:14'), last, SCHEDULE, ZoneInfo('UTC'), {'gmail'}) == ['gmail_inbox_scan']
    assert s.due_jobs(utc('2027-01-01T10:15'), last, SCHEDULE, ZoneInfo('UTC'), {'gmail'}) == ['gmail_sent_poll', 'gmail_inbox_scan']
    assert 'gmail_sent_poll' in s.due_jobs(utc('2027-01-01T00:00'), {}, SCHEDULE, ZoneInfo('UTC'), {'gmail'})


def test_daily_local_slot_and_offset():
    s = module()
    tz = ZoneInfo('Asia/Kolkata')
    last = {j['id']: utc('2026-12-31T02:00').isoformat() for j in s.JOBS}
    assert 'gmail_inbox_scan' not in s.due_jobs(utc('2027-01-01T01:29'), last, SCHEDULE, tz, {'gmail'})
    assert s.due_jobs(utc('2027-01-01T01:29'), last, SCHEDULE, tz, {'agentmail'}) == []
    assert 'gmail_inbox_scan' in s.due_jobs(utc('2027-01-01T01:30'), last, SCHEDULE, tz, {'gmail'})
    assert s.due_jobs(utc('2027-01-01T01:34'), last, SCHEDULE, tz, {'agentmail'}) == []
    assert s.due_jobs(utc('2027-01-01T01:35'), last, SCHEDULE, tz, {'agentmail'}) == ['agentmail_inbox_scan']


def test_catchup_is_once_and_readiness_gates():
    s = module()
    now = utc('2027-01-05T12:00')
    last = {'gmail_inbox_scan': utc('2027-01-01T08:00').isoformat()}
    assert s.due_jobs(now, last, SCHEDULE, ZoneInfo('UTC'), set()) == []
    assert s.due_jobs(now, last, SCHEDULE, ZoneInfo('UTC'), {'gmail'}).count('gmail_inbox_scan') == 1
    last['gmail_inbox_scan'] = now.isoformat()
    assert 'gmail_inbox_scan' not in s.due_jobs(now, last, SCHEDULE, ZoneInfo('UTC'), {'gmail'})


@pytest.mark.parametrize('day,start,expected', [('2027-03-28', '00:00', '2027-03-28T01:30'), ('2027-10-31', '00:00', '2027-10-31T00:30')])
def test_dst_daily_runs_once(day, start, expected):
    s = module()
    schedule = {**SCHEDULE, 'inbox_scan': '02:30'}
    last = {'agentmail_inbox_scan': utc(day + 'T12:00') - timedelta(days=1)}
    ran = []
    for minute in range(241):
        now = utc(day + 'T' + start) + timedelta(minutes=minute)
        if s.due_jobs(now, last, schedule, ZoneInfo('Europe/Paris'), {'agentmail'}):
            ran.append(now)
            last['agentmail_inbox_scan'] = now.isoformat()
    # AgentMail has a five-minute offset.
    assert ran == [utc(expected) + timedelta(minutes=5)]


@pytest.mark.parametrize('now,expected', [('2027-03-27T08:00', '2027-03-28T05:00'), ('2027-10-30T08:00', '2027-10-31T06:00')])
def test_next_run_preserves_local_calendar_clock(now, expected):
    assert module().next_run(job('gmail_inbox_scan'), utc(now), utc(now), SCHEDULE, ZoneInfo('Europe/Paris')) == utc(expected)


def test_next_run_fold_and_offset_midnight():
    s = module()
    fold = {**SCHEDULE, 'inbox_scan': '02:30'}
    now = utc('2027-10-31T01:00')
    assert s.next_run(job('gmail_inbox_scan'), now, utc('2027-10-31T00:30'), fold, ZoneInfo('Europe/Paris')) == utc('2027-11-01T01:30')
    schedule = {**SCHEDULE, 'inbox_scan': '23:58'}
    now = utc('2027-01-02T00:02')
    assert s.next_run(job('agentmail_inbox_scan'), now, utc('2027-01-01T00:03'), schedule, ZoneInfo('UTC')) == utc('2027-01-02T00:03')


def test_sourcing_and_fixed_queue_slots():
    s = module()
    tz = ZoneInfo('Asia/Kolkata')
    last = {j['id']: utc('2027-01-01T12:00').isoformat() for j in s.JOBS}
    assert s.due_jobs(utc('2027-01-01T23:00'), last, SCHEDULE, tz, {'apify_ready', 'saved_jobs'}) == ['job_sourcing', 'saved_jobs_queue']
    assert s.next_run(job('saved_jobs_queue'), utc('2027-01-01T12:00'), last['saved_jobs_queue'], SCHEDULE, tz) == utc('2027-01-01T21:30')
    assert s.due_jobs(utc('2027-01-01T22:59'), last, SCHEDULE, tz, {'apify_ready'}) == []


@pytest.mark.parametrize('raw', [None, '{bad', '[]', '{"last_runs": [], "results": {}}', '{"last_runs": {"gmail_sent_poll": "bad"}, "results": {}}'])
def test_missing_or_corrupt_state(raw):
    if raw is not None:
        paths.scheduler_state_path().write_text(raw, encoding='utf-8')
    assert module().load_state() == {'last_runs': {}, 'results': {}}


def test_ready_set_and_missing_profile(monkeypatch):
    s = module()
    monkeypatch.setattr(s.integrations, 'connected_ids', lambda: {'apify', 'gmail'})
    monkeypatch.setenv('SAVED_JOBS_WEBHOOK_SECRET', 'fixture-webhook')
    monkeypatch.setattr(s.source_jobs, 'sourcing_ready', lambda: True)
    assert s.ready_set() == {'apify', 'gmail', 'apify_ready', 'saved_jobs'}
    monkeypatch.undo()
    paths.profile_path().unlink()
    for name in settings.ENV_MAP:
        monkeypatch.delenv(name, raising=False)
    assert s._profile_tz() == ZoneInfo('UTC')
    assert s.ready_set() == set()


def test_runner_failure_continues_and_persists_private_state(monkeypatch, capsys):
    s = module()
    monkeypatch.setattr(s, 'ready_set', lambda: {'gmail', 'agentmail', 'apify_ready', 'saved_jobs'})
    now = utc('2027-01-01T12:00')
    calls = []
    def runner(command, **kwargs):
        calls.append((command, kwargs))
        if command[1].endswith('poll_gmail_sent.py'):
            raise RuntimeError('fixture-private-exception-text')
        return SimpleNamespace(returncode=2 if command[1].endswith('source_jobs.py') else 0)
    ids = s.run_once(now, runner=runner)
    assert ids == [j['id'] for j in s.JOBS]
    assert len(calls) == 5
    assert all(c[1] == {'cwd': paths.repo_dir(), 'timeout': 1800} for c in calls)
    assert all(os.path.isabs(c[0][1]) for c in calls)
    state = s.load_state()
    assert all(v == now.isoformat() for v in state['last_runs'].values())
    assert state['results']['gmail_sent_poll'] == {'ok': False, 'exit_code': None, 'at': now.isoformat()}
    assert state['results']['job_sourcing']['exit_code'] == 2
    assert state['results']['saved_jobs_queue']['ok'] is True
    assert json.loads(paths.scheduler_state_path().read_text(encoding='utf-8')) == state
    assert not list(paths.data_dir().glob('tmp*'))
    assert s.run_once(now, runner=runner) == []
    captured = capsys.readouterr()
    assert 'gmail_sent_poll' in captured.out and 'RuntimeError' in captured.out
    assert 'job_sourcing' in captured.out and 'exit code 2' in captured.out
    assert 'fixture-private-exception-text' not in captured.out + captured.err


def test_main_reports_sanitized_cycle_failure_on_stdout(monkeypatch, capsys):
    s = module()
    def fail():
        raise RuntimeError('fixture-private-cycle-text')
    def stop(seconds):
        assert seconds == 60
        raise KeyboardInterrupt
    monkeypatch.setattr(s, 'run_once', fail)
    monkeypatch.setattr(s.time, 'sleep', stop)
    with pytest.raises(KeyboardInterrupt):
        s.main()
    captured = capsys.readouterr()
    assert 'Scheduler cycle failed' in captured.out and 'RuntimeError' in captured.out
    assert 'fixture-private-cycle-text' not in captured.out + captured.err


def test_scheduler_endpoint_reports_all_jobs_without_running(client, monkeypatch):
    s = module()
    monkeypatch.setattr(s, 'ready_set', lambda: {'gmail'})
    monkeypatch.setattr(s, 'run_once', lambda *a, **k: pytest.fail('GET must not run jobs'))
    response = client.get('/api/scheduler')
    assert response.status_code == 200
    rows = response.get_json()
    assert [r['id'] for r in rows] == [j['id'] for j in s.JOBS]
    assert all(set(r) == {'id', 'enabled', 'last_run', 'next_run', 'last_result'} for r in rows)
    assert [r['enabled'] for r in rows] == [True, True, False, False, False]
    assert all(datetime.fromisoformat(r['next_run']).tzinfo for r in rows)
