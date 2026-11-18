import os

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("SENDER_EMAIL", "noreply@example.com")
os.environ.setdefault("TUTOR_EMAIL", "tutor@example.com")

import marker  # noqa: E402
import notifier  # noqa: E402


def test_marker_scores_only_correct_mcqs():
    qs = [{"id": 1, "kind": "mcq", "correct_option": "A", "marks": 1},
          {"id": 2, "kind": "short", "correct_option": None, "marks": 2}]
    assert marker.mark_mcq(qs, {1: "A", 2: "text"}) == 1


def test_notifier_emails_tutor_for_upload(monkeypatch):
    sent = []
    monkeypatch.setattr(notifier, "_send", lambda to, subject, body: sent.append((to, subject, body)))
    event = {"Records": [{"s3": {"object": {"key": "submissions/7/stu-1/abc.pdf", "size": 40 * 1024 * 1024}}}]}
    assert notifier.handler(event, None) == {"emails_sent": 1}
    to, subject, body = sent[0]
    assert to == "tutor@example.com" and "assignment 7" in subject and "40.0 MB" in body


def test_notifier_emails_students_when_results_released(monkeypatch):
    sent = []
    monkeypatch.setattr(notifier, "_send", lambda to, subject, body: sent.append(to))
    notifier.handler({"type": "results_released", "exam_title": "Demo", "recipients": ["a@x.com", "b@x.com"]}, None)
    assert sent == ["a@x.com", "b@x.com"]
