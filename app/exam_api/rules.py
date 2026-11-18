"""Pure business rules (no AWS, no database) - easy to unit test."""
import re
import uuid
from datetime import datetime, timedelta

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "application/zip": "zip",
    "application/x-zip-compressed": "zip",
}
AUTOSAVE_GRACE = timedelta(seconds=30)  # accept the last autosave that was in flight at the deadline


class RuleError(ValueError):
    """A request that breaks a rule -> HTTP 400/403."""


def validate_upload(content_type: str, size_bytes: int, due_at: datetime, now: datetime) -> str:
    """Check an assignment upload request. Returns the file extension."""
    if content_type not in ALLOWED_TYPES:
        raise RuleError("Only PDF or ZIP files are allowed")
    if size_bytes <= 0 or size_bytes > MAX_UPLOAD_BYTES:
        raise RuleError("File must be between 1 byte and 50 MB")
    if now > due_at:
        raise RuleError("The deadline has passed")
    return ALLOWED_TYPES[content_type]


def submission_key(assignment_id: int, student_id: str, ext: str) -> str:
    """S3 object key: submissions/<assignment>/<student>/<uuid>.<ext>"""
    safe_student = re.sub(r"[^A-Za-z0-9-]", "", student_id)
    return f"submissions/{assignment_id}/{safe_student}/{uuid.uuid4()}.{ext}"


def attempt_deadline(started_at: datetime, duration_minutes: int, closes_at: datetime) -> datetime:
    """A student gets the full duration, but never past the exam's closing time."""
    return min(started_at + timedelta(minutes=duration_minutes), closes_at)


def can_autosave(deadline: datetime, submitted: bool, now: datetime) -> bool:
    return not submitted and now <= deadline + AUTOSAVE_GRACE


def mark_mcq(questions: list[dict], answers: dict) -> int:
    """Score MCQs. questions: [{id, kind, correct_option, marks}], answers: {question_id: answer}."""
    score = 0
    for q in questions:
        if q["kind"] == "mcq" and answers.get(q["id"]) == q["correct_option"]:
            score += q.get("marks", 1)
    return score
