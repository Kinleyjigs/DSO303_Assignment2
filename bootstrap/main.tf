# One-time setup (run locally once): Terraform state bucket + GitHub Actions OIDC deploy role.
#   cd bootstrap && terraform init && terraform apply -var github_repo=<owner>/<repo>

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "prefix" {
  description = "Unique prefix so this deployment cannot clash with others in a shared account"
  type        = string
  default     = "yonten"
}

variable "github_repo" {
  description = "GitHub repository allowed to deploy, as owner/repo"
  type        = string
}

data "aws_caller_identity" "me" {}

locals {
  gh_owner = split("/", var.github_repo)[0]
  gh_repo  = split("/", var.github_repo)[1]
}

# ---------- Terraform remote state ----------
resource "aws_s3_bucket" "state" {
  bucket        = "${var.prefix}-tfstate-${data.aws_caller_identity.me.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------- GitHub Actions OIDC (no long-lived AWS keys in GitHub) ----------
# An AWS account can have only one GitHub OIDC provider. This account already has one,
# so we use it (read-only) instead of creating it. Terraform will never change or delete it.
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "github_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only the main branch of this one repository can deploy.
    # GitHub sends either the classic subject (repo:owner/repo:...) or the newer
    # immutable one with IDs (repo:owner@123/repo@456:...), so accept both forms.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_repo}:ref:refs/heads/main",
        "repo:${local.gh_owner}@*/${local.gh_repo}@*:ref:refs/heads/main",
      ]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "${var.prefix}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_trust.json
}

# Terraform creates IAM roles, VPCs, RDS, etc., so the pipeline needs broad rights.
# In production, replace with a scoped policy and a permissions boundary.
resource "aws_iam_role_policy_attachment" "github_deploy_admin" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}

output "deploy_role_arn" {
  value = aws_iam_role.github_deploy.arn
}
