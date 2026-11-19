terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # bucket is passed at init: terraform init -backend-config="bucket=<state bucket from bootstrap>"
  backend "s3" {
    key          = "yonten/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "exam-platform"
      ManagedBy = "terraform"
    }
  }
}

# CloudFront-scoped WAF and CloudFront certificates must live in us-east-1
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
  default_tags {
    tags = {
      Project   = "exam-platform"
      ManagedBy = "terraform"
    }
  }
}
