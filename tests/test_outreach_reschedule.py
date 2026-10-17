from datetime import date, timedelta

from outreach_manager import apply_weekend_skip, reschedule_from_new_base


def test_reschedule_from_new_base_reanchors_day_offsets_and_weekend_skips():
    # sequence_num 4 = Email 2 (day-offset 5), sequence_num 5 = Email 3 (day-offset 12)
    pending = [(101, 4), (102, 5)]
    new_base = date(2026, 7, 15)

    updates = reschedule_from_new_base(pending, new_base)

    expected_101 = apply_weekend_skip(new_base + timedelta(days=5)).isoformat()
    expected_102 = apply_weekend_skip(new_base + timedelta(days=12)).isoformat()
    assert updates == [(101, expected_101), (102, expected_102)]


def test_reschedule_from_new_base_skips_unknown_sequence_numbers():
    pending = [(101, 999)]  # not a real sequence_num in _SCHEDULE
    updates = reschedule_from_new_base(pending, date(2026, 7, 15))
    assert updates == []


def test_reschedule_from_new_base_returns_empty_for_no_pending_entries():
    assert reschedule_from_new_base([], date(2026, 7, 15)) == []
