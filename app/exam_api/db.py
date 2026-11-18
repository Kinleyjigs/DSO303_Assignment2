"""PostgreSQL access. The password comes from Secrets Manager (RDS rotates it), cached for 5 minutes."""
import json
import os
import time
from contextlib import contextmanager

import boto3
import psycopg
from psycopg.rows import dict_row

_secret_cache: dict = {"value": None, "at": 0.0}
SCHEMA = """
CREATE TABLE IF NOT EXISTS exams (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    duration_minutes INT NOT NULL,
    opens_at TIMESTAMPTZ NOT NULL,
    closes_at TIMESTAMPTZ NOT NULL,
    results_released BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS questions (
    id SERIAL PRIMARY KEY,
    exam_id INT NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    position INT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('mcq', 'short')),
    text TEXT NOT NULL,
    options JSONB,
    correct_option TEXT,
    marks INT NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS attempts (
    id SERIAL PRIMARY KEY,
    exam_id INT NOT NULL REFERENCES exams(id),
    student_id TEXT NOT NULL,
    student_email TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deadline TIMESTAMPTZ NOT NULL,
    submitted_at TIMESTAMPTZ,
    mcq_score INT,
    UNIQUE (exam_id, student_id)
);
CREATE TABLE IF NOT EXISTS answers (
    attempt_id INT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    question_id INT NOT NULL REFERENCES questions(id),
    answer TEXT,
    saved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (attempt_id, question_id)
);
CREATE TABLE IF NOT EXISTS assignments (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    due_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions (
    id SERIAL PRIMARY KEY,
    assignment_id INT NOT NULL REFERENCES assignments(id),
    student_id TEXT NOT NULL,
    s3_key TEXT NOT NULL UNIQUE,
    size_bytes BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

SEED = """
INSERT INTO exams (title, duration_minutes, opens_at, closes_at)
VALUES ('DSO303 Demo Exam', 30, now() - interval '1 day', now() + interval '60 days');
INSERT INTO questions (exam_id, position, kind, text, options, correct_option, marks) VALUES
 (currval('exams_id_seq'), 1, 'mcq', 'Which service gives automatic database failover to a second AZ?',
  '["RDS Multi-AZ", "S3 versioning", "CloudFront", "NAT Gateway"]', 'RDS Multi-AZ', 1),
 (currval('exams_id_seq'), 2, 'mcq', 'Why do assignment uploads use presigned URLs?',
  '["Files go straight to S3, not through the API", "They make files public", "They skip encryption", "They are required by Cognito"]',
  'Files go straight to S3, not through the API', 1),
 (currval('exams_id_seq'), 3, 'short', 'In one sentence, what does SQS do in this design?', NULL, NULL, 2);
INSERT INTO assignments (title, due_at) VALUES ('Assignment 2 - Architecture', now() + interval '60 days');
"""


def _password() -> tuple[str, str]:
    if os.environ.get("DB_PASSWORD"):  # local development
        return os.environ.get("DB_USER", "postgres"), os.environ["DB_PASSWORD"]
    if not _secret_cache["value"] or time.time() - _secret_cache["at"] > 300:
        sm = boto3.client("secretsmanager")
        _secret_cache["value"] = json.loads(sm.get_secret_value(SecretId=os.environ["DB_SECRET_ARN"])["SecretString"])
        _secret_cache["at"] = time.time()
    s = _secret_cache["value"]
    return s["username"], s["password"]


@contextmanager
def connect():
    user, password = _password()
    ssl = {}
    if os.path.exists("/app/rds-ca.pem"):
        ssl = {"sslmode": "verify-full", "sslrootcert": "/app/rds-ca.pem"}
    try:
        conn = psycopg.connect(
            host=os.environ["DB_HOST"], dbname=os.environ.get("DB_NAME", "exam"),
            user=user, password=password, row_factory=dict_row, connect_timeout=5, **ssl,
        )
    except psycopg.OperationalError:
        _secret_cache["value"] = None  # password may have been rotated: fetch again next time
        raise
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_schema() -> None:
    """Create tables and demo data once. The advisory lock stops parallel tasks racing."""
    with connect() as conn:
        conn.execute("SELECT pg_advisory_lock(42)")
        try:
            conn.execute(SCHEMA)
            if conn.execute("SELECT count(*) AS n FROM exams").fetchone()["n"] == 0:
                conn.execute(SEED)
        finally:
            conn.execute("SELECT pg_advisory_unlock(42)")
