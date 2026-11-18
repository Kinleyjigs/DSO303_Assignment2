"""MCQ auto-marker. Triggered by the SQS marking-queue with {"attempt_id": N}."""
import json
import os
import ssl

import boto3
import pg8000.native

_secret = None


def mark_mcq(questions, answers):
    """questions: [{id, kind, correct_option, marks}], answers: {question_id: answer}"""
    return sum(q["marks"] for q in questions
               if q["kind"] == "mcq" and answers.get(q["id"]) == q["correct_option"])


def _connect():
    global _secret
    if _secret is None:
        sm = boto3.client("secretsmanager")
        _secret = json.loads(sm.get_secret_value(SecretId=os.environ["DB_SECRET_ARN"])["SecretString"])
    ctx = ssl.create_default_context(cafile=os.path.join(os.path.dirname(__file__), "rds-ca.pem"))
    return pg8000.native.Connection(
        user=_secret["username"], password=_secret["password"],
        host=os.environ["DB_HOST"], database=os.environ["DB_NAME"], ssl_context=ctx, timeout=10,
    )


def mark_attempt(conn, attempt_id):
    rows = conn.run(
        "SELECT q.id, q.kind, q.correct_option, q.marks FROM questions q "
        "JOIN attempts a ON a.exam_id = q.exam_id WHERE a.id = :a", a=attempt_id)
    questions = [{"id": r[0], "kind": r[1], "correct_option": r[2], "marks": r[3]} for r in rows]
    answers = {r[0]: r[1] for r in conn.run(
        "SELECT question_id, answer FROM answers WHERE attempt_id = :a", a=attempt_id)}
    score = mark_mcq(questions, answers)
    conn.run("UPDATE attempts SET mcq_score = :s WHERE id = :a", s=score, a=attempt_id)
    return score


def handler(event, _context):
    """Reports failed messages individually so only they are retried (then sent to the DLQ)."""
    failures = []
    conn = _connect()
    try:
        for record in event["Records"]:
            try:
                attempt_id = int(json.loads(record["body"])["attempt_id"])
                score = mark_attempt(conn, attempt_id)
                print(json.dumps({"attempt_id": attempt_id, "mcq_score": score}))
            except Exception as exc:  # noqa: BLE001
                print(json.dumps({"error": str(exc), "messageId": record["messageId"]}))
                failures.append({"itemIdentifier": record["messageId"]})
    finally:
        conn.close()
    return {"batchItemFailures": failures}
