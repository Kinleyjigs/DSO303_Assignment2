"""Email notifier.
- S3 ObjectCreated event (walkthrough 2): email the tutor about a new submission.
- {"type": "results_released", ...} from the API: email each student.
"""
import os
import urllib.parse

import boto3

ses = boto3.client("ses")


def _send(to, subject, body):
    ses.send_email(
        Source=os.environ["SENDER_EMAIL"],
        Destination={"ToAddresses": [to]},
        Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}},
    )


def describe_upload(record):
    """Turn an S3 event record into (assignment_id, student_id, filename, size_mb)."""
    key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
    _, assignment_id, student_id, filename = key.split("/", 3)
    size_mb = record["s3"]["object"].get("size", 0) / (1024 * 1024)
    return assignment_id, student_id, filename, round(size_mb, 1)


def handler(event, _context):
    sent = 0
    if event.get("type") == "results_released":
        for email in event.get("recipients", []):
            _send(email, f"Results released: {event['exam_title']}",
                  "Your exam results are now available. Sign in to the exam platform to view them.")
            sent += 1
    else:
        for record in event.get("Records", []):
            assignment_id, student_id, filename, size_mb = describe_upload(record)
            _send(os.environ["TUTOR_EMAIL"], f"New submission for assignment {assignment_id}",
                  f"Student {student_id} uploaded {filename} ({size_mb} MB).")
            sent += 1
    print({"emails_sent": sent})
    return {"emails_sent": sent}
