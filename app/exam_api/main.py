"""Exam platform API (runs on ECS Fargate behind the ALB; CloudFront sends /api/* here)."""
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import boto3
from botocore.config import Config
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import db, rules
from .auth import User, current_user, require

log = logging.getLogger("exam_api")
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.environ.get("SKIP_DB_INIT") != "1":
        try:
            db.init_schema()
        except Exception:  # keep serving /health; the next task start retries
            log.exception("Database initialisation failed")
    yield


app = FastAPI(title="Exam Platform API", lifespan=lifespan)


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---------- health ----------
@app.get("/health")
def health():
    return {"status": "ok"}


# ---------- exams (walkthrough 1) ----------
@app.get("/api/exams")
def list_exams(user: User = Depends(current_user)):
    with db.connect() as conn:
        exams = conn.execute(
            "SELECT id, title, duration_minutes, opens_at, closes_at, results_released FROM exams ORDER BY id"
        ).fetchall()
    return {"exams": exams, "user": {"email": user.email, "groups": user.groups}}


@app.post("/api/exams/{exam_id}/start")
def start_exam(exam_id: int, user: User = Depends(current_user)):
    require(user, "student")
    t = now()
    with db.connect() as conn:
        exam = conn.execute("SELECT * FROM exams WHERE id = %s", (exam_id,)).fetchone()
        if not exam:
            raise HTTPException(404, "Exam not found")
        if not exam["opens_at"] <= t <= exam["closes_at"]:
            raise HTTPException(403, "Exam is not open")
        deadline = rules.attempt_deadline(t, exam["duration_minutes"], exam["closes_at"])
        # The server records the start time, so the timer cannot be changed in the browser
        attempt = conn.execute(
            """INSERT INTO attempts (exam_id, student_id, student_email, deadline)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (exam_id, student_id) DO UPDATE SET exam_id = EXCLUDED.exam_id
               RETURNING id, deadline, submitted_at""",
            (exam_id, user.sub, user.email, deadline),
        ).fetchone()
        questions = conn.execute(
            "SELECT id, position, kind, text, options, marks FROM questions WHERE exam_id = %s ORDER BY position",
            (exam_id,),
        ).fetchall()  # the answer key is never sent to the browser
        saved = conn.execute(
            "SELECT question_id, answer FROM answers WHERE attempt_id = %s", (attempt["id"],)
        ).fetchall()
    return {
        "attempt_id": attempt["id"],
        "deadline": attempt["deadline"],
        "submitted": attempt["submitted_at"] is not None,
        "questions": questions,
        "saved_answers": {str(r["question_id"]): r["answer"] for r in saved},
    }


class AnswersIn(BaseModel):
    answers: dict[int, str] = Field(..., max_length=200)


def _own_attempt(conn, attempt_id: int, user: User) -> dict:
    attempt = conn.execute(
        "SELECT * FROM attempts WHERE id = %s AND student_id = %s", (attempt_id, user.sub)
    ).fetchone()
    if not attempt:
        raise HTTPException(404, "Attempt not found")
    return attempt


@app.put("/api/attempts/{attempt_id}/answers")
def autosave(attempt_id: int, body: AnswersIn, user: User = Depends(current_user)):
    """Called by the browser every 30 seconds with the changed answers (idempotent upsert)."""
    require(user, "student")
    t = now()
    with db.connect() as conn:
        attempt = _own_attempt(conn, attempt_id, user)
        if not rules.can_autosave(attempt["deadline"], attempt["submitted_at"] is not None, t):
            raise HTTPException(403, "Time is up or the exam was already submitted")
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO answers (attempt_id, question_id, answer, saved_at)
                   SELECT %s, q.id, %s, now() FROM questions q
                   WHERE q.id = %s AND q.exam_id = %s
                   ON CONFLICT (attempt_id, question_id)
                   DO UPDATE SET answer = EXCLUDED.answer, saved_at = now()""",
                [(attempt_id, ans[:5000], qid, attempt["exam_id"]) for qid, ans in body.answers.items()],
            )
    return {"saved": len(body.answers), "saved_at": t}


@app.post("/api/attempts/{attempt_id}/submit")
def submit(attempt_id: int, user: User = Depends(current_user)):
    require(user, "student")
    with db.connect() as conn:
        attempt = _own_attempt(conn, attempt_id, user)
        if attempt["submitted_at"] is None:
            conn.execute("UPDATE attempts SET submitted_at = now() WHERE id = %s", (attempt_id,))
    # Marking happens asynchronously: SQS -> auto-marker Lambda
    boto3.client("sqs").send_message(
        QueueUrl=os.environ["MARKING_QUEUE_URL"], MessageBody=json.dumps({"attempt_id": attempt_id})
    )
    return {"status": "submitted", "marking": "queued"}


@app.get("/api/attempts/{attempt_id}/result")
def result(attempt_id: int, user: User = Depends(current_user)):
    with db.connect() as conn:
        attempt = _own_attempt(conn, attempt_id, user)
        exam = conn.execute("SELECT results_released FROM exams WHERE id = %s", (attempt["exam_id"],)).fetchone()
    if not exam["results_released"]:
        raise HTTPException(403, "Results have not been released yet")
    return {"attempt_id": attempt_id, "mcq_score": attempt["mcq_score"]}


@app.post("/api/exams/{exam_id}/release")
def release_results(exam_id: int, user: User = Depends(current_user)):
    require(user, "tutor")
    with db.connect() as conn:
        exam = conn.execute(
            "UPDATE exams SET results_released = TRUE WHERE id = %s RETURNING title", (exam_id,)
        ).fetchone()
        if not exam:
            raise HTTPException(404, "Exam not found")
        emails = [r["student_email"] for r in conn.execute(
            "SELECT student_email FROM attempts WHERE exam_id = %s AND submitted_at IS NOT NULL", (exam_id,)
        ).fetchall()]
    # Asynchronous invoke: the API returns immediately, the notifier sends the emails
    boto3.client("lambda").invoke(
        FunctionName=os.environ["NOTIFIER_FUNCTION"],
        InvocationType="Event",
        Payload=json.dumps({"type": "results_released", "exam_title": exam["title"], "recipients": emails}),
    )
    return {"released": True, "emails_queued": len(emails)}


# ---------- assignments (walkthrough 2) ----------
@app.get("/api/assignments")
def list_assignments(user: User = Depends(current_user)):
    with db.connect() as conn:
        return {"assignments": conn.execute("SELECT id, title, due_at FROM assignments ORDER BY id").fetchall()}


class UploadRequest(BaseModel):
    filename: str = Field(..., max_length=200)
    content_type: str
    size_bytes: int


@app.post("/api/assignments/{assignment_id}/upload-url")
def upload_url(assignment_id: int, body: UploadRequest, user: User = Depends(current_user)):
    """Checks the request and returns a presigned POST so the browser uploads straight to S3."""
    require(user, "student")
    with db.connect() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = %s", (assignment_id,)).fetchone()
        if not assignment:
            raise HTTPException(404, "Assignment not found")
        try:
            ext = rules.validate_upload(body.content_type, body.size_bytes, assignment["due_at"], now())
        except rules.RuleError as exc:
            raise HTTPException(400, str(exc)) from exc
        key = rules.submission_key(assignment_id, user.sub, ext)
        conn.execute(
            "INSERT INTO submissions (assignment_id, student_id, s3_key, size_bytes) VALUES (%s, %s, %s, %s)",
            (assignment_id, user.sub, key, body.size_bytes),
        )
    # KMS-encrypted buckets only accept Signature Version 4, and a regional endpoint keeps the signature valid
    s3 = boto3.client("s3", region_name=os.environ["AWS_REGION"], config=Config(signature_version="s3v4"),
                      endpoint_url=f"https://s3.{os.environ['AWS_REGION']}.amazonaws.com")
    post = s3.generate_presigned_post(
        Bucket=os.environ["SUBMISSIONS_BUCKET"],
        Key=key,
        Fields={"Content-Type": body.content_type},
        Conditions=[
            {"Content-Type": body.content_type},
            ["content-length-range", 1, rules.MAX_UPLOAD_BYTES],  # S3 itself rejects files over 50 MB
        ],
        ExpiresIn=300,  # 5 minutes
    )
    return {"upload": post, "key": key}
