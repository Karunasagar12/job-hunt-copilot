"""Run the five fixed background jobs using local-calendar schedules."""
from datetime import datetime, time as local_time, timedelta, timezone
import json
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

import integrations
import paths
import profile as prof
import settings
import source_jobs

JOBS = [
    {'id': 'gmail_sent_poll', 'script': 'poll_gmail_sent.py', 'kind': 'interval',
     'schedule_key': 'gmail_sent_poll_minutes', 'offset_min': 0, 'requires': 'gmail'},
    {'id': 'gmail_inbox_scan', 'script': 'poll_gmail_inbox.py', 'kind': 'daily',
     'schedule_key': 'inbox_scan', 'offset_min': 0, 'requires': 'gmail'},
    {'id': 'agentmail_inbox_scan', 'script': 'poll_agentmail_inbox.py', 'kind': 'daily',
     'schedule_key': 'inbox_scan', 'offset_min': 5, 'requires': 'agentmail'},
    {'id': 'job_sourcing', 'script': 'source_jobs.py', 'kind': 'daily',
     'schedule_key': 'job_sourcing', 'offset_min': 0, 'requires': 'apify_ready'},
    {'id': 'saved_jobs_queue', 'script': 'process_saved_jobs_queue.py', 'kind': 'daily',
     'schedule_key': None, 'fixed_time': '03:00', 'offset_min': 0, 'requires': 'saved_jobs'},
]


def _utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Scheduler timestamps must include a timezone')
    return value.astimezone(timezone.utc)


def _slot(job, day, schedule, tz):
    clock = local_time.fromisoformat(job.get('fixed_time') or schedule[job['schedule_key']])
    local = datetime.combine(day, clock) + timedelta(minutes=job['offset_min'])
    # fold=0 chooses the first occurrence; round-tripping through UTC moves
    # nonexistent spring times forward by the daylight-saving gap.
    return local.replace(tzinfo=tz, fold=0).astimezone(timezone.utc)


def _daily_slots(job, now, schedule, tz):
    day = now.astimezone(tz).date()
    # Include yesterday's base date because a job offset may cross midnight.
    slots = [_slot(job, day + timedelta(days=delta), schedule, tz)
             for delta in (-2, -1, 0, 1)]
    return max(slot for slot in slots if slot <= now), min(slot for slot in slots if slot > now)


def next_run(job, now_utc, last_run, schedule, tz):
    """Return now when due, otherwise the next UTC instant for this job."""
    now = _utc(now_utc)
    last = _utc(last_run) if last_run is not None else None
    if job['kind'] == 'interval':
        interval = timedelta(minutes=float(schedule[job['schedule_key']]))
        if interval <= timedelta(0):
            raise ValueError('Polling interval must be positive')
        return now if last is None else max(now, last + interval)
    latest, upcoming = _daily_slots(job, now, schedule, tz)
    return now if last is None or last < latest else upcoming


def due_jobs(now_utc, last_runs, schedule, tz, ready):
    """Calculate due job IDs without reading configuration or running jobs."""
    now = _utc(now_utc)
    return [job['id'] for job in JOBS if job['requires'] in ready
            and next_run(job, now, last_runs.get(job['id']), schedule, tz) <= now]


def _profile_tz():
    try:
        return ZoneInfo(prof.load_profile()['timezone'])
    except prof.ProfileError:
        return ZoneInfo('UTC')


def ready_set():
    ready = set(integrations.connected_ids())
    if 'apify' in ready and source_jobs.sourcing_ready():
        ready.add('apify_ready')
    if settings.get('webhooks.saved_jobs_secret'):
        ready.add('saved_jobs')
    return ready


def load_state():
    """Recover safely from a missing, truncated, or invalid state file."""
    try:
        state = json.loads(paths.scheduler_state_path().read_text(encoding='utf-8'))
        if not isinstance(state, dict) or not all(isinstance(state.get(k), dict) for k in ('last_runs', 'results')):
            raise ValueError('Invalid scheduler state')
        for stamp in state['last_runs'].values():
            _utc(stamp)
        return state
    except (OSError, ValueError, TypeError, AttributeError):
        return {'last_runs': {}, 'results': {}}


def _save_state(state):
    # NamedTemporaryFile gives each writer a unique temporary name and private
    # permissions; replacement is atomic for concurrent API readers.
    prof._atomic_write(paths.scheduler_state_path(), json.dumps(state, indent=2) + '\n')
    settings._chmod_private(paths.scheduler_state_path())


def run_once(now_utc=None, runner=subprocess.run):
    now = _utc(now_utc if now_utc is not None else datetime.now(timezone.utc))
    state = load_state()
    ids = due_jobs(now, state['last_runs'], settings.get('schedule'), _profile_tz(), ready_set())
    for job in JOBS:
        if job['id'] not in ids:
            continue
        code = None
        try:
            result = runner([sys.executable, str(paths.repo_dir() / job['script'])],
                            cwd=paths.repo_dir(), timeout=1800)
            code = result.returncode
            if code != 0:
                print(f"Scheduled job {job['id']} failed: exit code {code}", flush=True)
            else:
                print(f"Scheduled job {job['id']} finished", flush=True)
        except Exception as exc:
            # Exception text may contain provider credentials or private data.
            print(f"Scheduled job {job['id']} failed: {type(exc).__name__}", flush=True)
        stamp = now.isoformat()
        state['last_runs'][job['id']] = stamp
        state['results'][job['id']] = {'ok': code == 0, 'exit_code': code, 'at': stamp}
        _save_state(state)
    return ids


def main():
    print('[scheduler] started; checking for due jobs every 60s', flush=True)
    while True:
        try:
            run_once()
        except Exception as exc:
            print(f'Scheduler cycle failed: {type(exc).__name__}', flush=True)
        time.sleep(60)


if __name__ == '__main__':
    main()
