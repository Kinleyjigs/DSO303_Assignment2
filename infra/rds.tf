# RDS PostgreSQL Multi-AZ: primary in one AZ, synchronous standby in the other

resource "aws_db_subnet_group" "main" {
  name       = "${var.name}-db-subnets"
  subnet_ids = aws_subnet.db[*].id
}

resource "aws_db_parameter_group" "pg16" {
  name   = "${var.name}-pg16"
  family = "postgres16"

  parameter {
    name  = "rds.force_ssl" # encryption in transit to the database
    value = "1"
  }
}

resource "aws_db_instance" "main" {
  identifier            = "${var.name}-db"
  engine                = "postgres"
  engine_version        = "16"
  instance_class        = var.db_instance_class
  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"

  db_name  = "exam"
  username = "examadmin"
  # RDS stores the password in Secrets Manager and rotates it automatically
  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.main.arn

  multi_az               = true
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  parameter_group_name   = aws_db_parameter_group.pg16.name

  storage_encrypted = true
  kms_key_id        = aws_kms_key.main.arn

  backup_retention_period = 1 # free-plan maximum; point-in-time restore for the last 24 h (5-year copies: AWS Backup)
  copy_tags_to_snapshot   = true
  deletion_protection     = var.db_deletion_protection
  skip_final_snapshot     = true
  apply_immediately       = true
}

locals {
  db_secret_arn = aws_db_instance.main.master_user_secret[0].secret_arn
}
