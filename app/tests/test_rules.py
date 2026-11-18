from datetime import datetime, timedelta, timezone

import pytest

from exam_api import rules

NOW = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)


def test_pdf_under_50mb_is_accepted():
    assert rules.validate_upload("application/pdf", 40 * 1024 * 1024, NOW + timedelta(days=1), NOW) == "pdf"


def test_zip_is_accepted():
    assert rules.validate_upload("application/zip", 1000, NOW + timedelta(days=1), NOW) == "zip"


@pytest.mark.parametrize("ctype,size", [
    ("image/png", 1000),                   # wrong type
    ("application/pdf", 51 * 1024 * 1024),  # over 50 MB
    ("application/pdf", 0),                 # empty
])
def test_bad_uploads_are_rejected(ctype, size):
    with pytest.raises(rules.RuleError):
        rules.validate_upload(ctype, size, NOW + timedelta(days=1), NOW)


def test_late_upload_is_rejected():
    with pytest.raises(rules.RuleError):
        rules.validate_upload("application/pdf", 1000, NOW - timedelta(minutes=1), NOW)


def test_submission_key_layout():
    key = rules.submission_key(7, "abc-123", "pdf")
    assert key.startswith("submissions/7/abc-123/") and key.endswith(".pdf")


def test_deadline_never_passes_closing_time():
    closes = NOW + timedelta(minutes=10)
    assert rules.attempt_deadline(NOW, 30, closes) == closes
    assert rules.attempt_deadline(NOW, 30, NOW + timedelta(hours=2)) == NOW + timedelta(minutes=30)


def test_autosave_window():
    deadline = NOW
    assert rules.can_autosave(deadline, False, NOW + timedelta(seconds=20))
    assert not rules.can_autosave(deadline, False, NOW + timedelta(seconds=60))
    assert not rules.can_autosave(deadline, True, NOW - timedelta(minutes=5))


def test_mcq_marking():
    questions = [
        {"id": 1, "kind": "mcq", "correct_option": "A", "marks": 1},
        {"id": 2, "kind": "mcq", "correct_option": "B", "marks": 2},
        {"id": 3, "kind": "short", "correct_option": None, "marks": 5},
    ]
    assert rules.mark_mcq(questions, {1: "A", 2: "C", 3: "anything"}) == 1
    assert rules.mark_mcq(questions, {1: "A", 2: "B"}) == 3
