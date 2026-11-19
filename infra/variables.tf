variable "region" {
  description = "AWS region for the platform"
  type        = string
  default     = "us-east-1"
}

variable "name" {
  description = "Prefix for every resource name (unique, so it cannot clash with other deployments in the account)"
  type        = string
  default     = "yonten"
}

variable "image_tag" {
  description = "API image tag in ECR (the pipeline passes the git commit SHA)"
  type        = string
  default     = "latest"
}

variable "sender_email" {
  description = "Email address SES sends from (must be verified - SES emails a confirmation link)"
  type        = string
}

variable "tutor_email" {
  description = "Tutor address that receives 'new submission' emails (verified while SES is in sandbox)"
  type        = string
}

variable "alert_email" {
  description = "Optional address for CloudWatch alarm emails"
  type        = string
  default     = ""
}

variable "domain_name" {
  description = "Optional custom domain (e.g. exams.uni.edu). Leave empty to use the CloudFront domain."
  type        = string
  default     = ""
}

variable "hosted_zone_id" {
  description = "Route 53 hosted zone ID for domain_name (required when domain_name is set)"
  type        = string
  default     = ""
}

variable "api_min_tasks" {
  description = "Normal minimum number of API tasks (spread over both AZs)"
  type        = number
  default     = 2
}

variable "api_max_tasks" {
  description = "Maximum API tasks during peaks"
  type        = number
  default     = 20
}

variable "exam_min_tasks" {
  description = "Minimum API tasks during an exam window (pre-scaled so one AZ can carry the peak)"
  type        = number
  default     = 8
}

variable "exam_warmup_schedule" {
  description = "When to pre-scale before exams (Application Auto Scaling cron, UTC)"
  type        = string
  default     = "cron(45 2 ? * MON-FRI *)" # 08:45 Bhutan time, 15 min before a 09:00 exam
}

variable "exam_cooldown_schedule" {
  description = "When to drop back to normal capacity (UTC)"
  type        = string
  default     = "cron(0 6 ? * MON-FRI *)"
}

variable "db_instance_class" {
  description = "RDS instance class (db.t4g.medium in production; micro keeps the demo cheap)"
  type        = string
  default     = "db.t4g.micro"
}

variable "db_deletion_protection" {
  description = "Protect the database from deletion (set true in production)"
  type        = bool
  default     = false
}
