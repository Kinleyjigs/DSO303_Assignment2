# Asynchronous processing: SQS marking queue -> auto-marker Lambda; S3 upload -> notifier Lambda -> SES

# ---------- Queues ----------
resource "aws_sqs_queue" "marking_dlq" {
  name                      = "${var.name}-marking-dlq"
  kms_master_key_id         = aws_kms_key.main.id
  message_retention_seconds = 1209600 # 14 days to investigate failures
}

resource "aws_sqs_queue" "marking" {
  name                       = "${var.name}-marking"
  kms_master_key_id          = aws_kms_key.main.id
  visibility_timeout_seconds = 180 # 6 x the Lambda timeout
  message_retention_seconds  = 345600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.marking_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_sqs_queue" "notify_dlq" {
  name                    = "${var.name}-notify-dlq"
  sqs_managed_sse_enabled = true
}

# ---------- Lambda packages ----------
# build/marker is created by scripts/build_lambdas.sh (adds the pg8000 driver + RDS CA bundle)
data "archive_file" "marker" {
  type        = "zip"
  source_dir  = "${path.module}/../build/marker"
  output_path = "${path.module}/../build/marker.zip"
}

data "archive_file" "notifier" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/notifier"
  output_path = "${path.module}/../build/notifier.zip"
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# ---------- MCQ auto-marker (in the VPC so it can reach RDS) ----------
resource "aws_iam_role" "marker" {
  name               = "${var.name}-marker-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy_attachment" "marker_vpc" {
  role       = aws_iam_role.marker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

data "aws_iam_policy_document" "marker" {
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.marking.arn]
  }
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [local.db_secret_arn]
  }
  statement {
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.main.arn]
  }
}

resource "aws_iam_role_policy" "marker" {
  name   = "marker"
  role   = aws_iam_role.marker.id
  policy = data.aws_iam_policy_document.marker.json
}

resource "aws_cloudwatch_log_group" "marker" {
  name              = "/aws/lambda/${var.name}-marker"
  retention_in_days = 90
}

resource "aws_lambda_function" "marker" {
  function_name    = "${var.name}-marker"
  role             = aws_iam_role.marker.arn
  runtime          = "python3.12"
  handler          = "marker.handler"
  filename         = data.archive_file.marker.output_path
  source_code_hash = data.archive_file.marker.output_base64sha256
  memory_size      = 512
  timeout          = 30

  vpc_config {
    subnet_ids         = aws_subnet.app[*].id
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      DB_HOST       = aws_db_instance.main.address
      DB_NAME       = aws_db_instance.main.db_name
      DB_SECRET_ARN = local.db_secret_arn
    }
  }

  depends_on = [aws_cloudwatch_log_group.marker, aws_iam_role_policy_attachment.marker_vpc]
}

resource "aws_lambda_event_source_mapping" "marking" {
  event_source_arn        = aws_sqs_queue.marking.arn
  function_name           = aws_lambda_function.marker.arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]
  depends_on              = [aws_iam_role_policy.marker]
}

# ---------- Notifier (invoked by S3 and by the API when results are released) ----------
resource "aws_iam_role" "notifier" {
  name               = "${var.name}-notifier-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy_attachment" "notifier_logs" {
  role       = aws_iam_role.notifier.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "notifier" {
  statement {
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = ["*"]
  }
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.notify_dlq.arn]
  }
}

resource "aws_iam_role_policy" "notifier" {
  name   = "notifier"
  role   = aws_iam_role.notifier.id
  policy = data.aws_iam_policy_document.notifier.json
}

resource "aws_cloudwatch_log_group" "notifier" {
  name              = "/aws/lambda/${var.name}-notifier"
  retention_in_days = 90
}

resource "aws_lambda_function" "notifier" {
  function_name    = "${var.name}-notifier"
  role             = aws_iam_role.notifier.arn
  runtime          = "python3.12"
  handler          = "notifier.handler"
  filename         = data.archive_file.notifier.output_path
  source_code_hash = data.archive_file.notifier.output_base64sha256
  memory_size      = 256
  timeout          = 30

  environment {
    variables = {
      SENDER_EMAIL = var.sender_email
      TUTOR_EMAIL  = var.tutor_email
    }
  }

  depends_on = [aws_cloudwatch_log_group.notifier]
}

resource "aws_lambda_function_event_invoke_config" "notifier" {
  function_name          = aws_lambda_function.notifier.function_name
  maximum_retry_attempts = 2
  destination_config {
    on_failure {
      destination = aws_sqs_queue.notify_dlq.arn
    }
  }
  depends_on = [aws_iam_role_policy.notifier]
}

resource "aws_lambda_permission" "s3_invoke_notifier" {
  statement_id   = "AllowS3Invoke"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.notifier.function_name
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.submissions.arn
  source_account = data.aws_caller_identity.me.account_id
}

# ---------- SES: verify sender (and tutor while the account is in the SES sandbox) ----------
resource "aws_sesv2_email_identity" "emails" {
  for_each       = toset([var.sender_email, var.tutor_email])
  email_identity = each.value
}
