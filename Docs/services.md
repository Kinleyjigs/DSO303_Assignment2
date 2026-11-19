# Task 2 – Service Documentation

Every service in the architecture (see the Cloud Architecture Lab canvas, [`Evidence/01-full-canvas.png`](../Evidence/01-full-canvas.png)) is listed below. Each one is justified against a real alternative and given the configuration used in this design.

## Edge, frontend and authentication

| Service | Role | Why over an alternative | Configuration | Connects to |
|---|---|---|---|---|
| **Amazon Route 53** | DNS for `exams.uni.edu` | Alias records point straight at CloudFront with no extra lookup, and DNS sits on the same AWS account as the rest, unlike an external DNS provider. Route 53 has a 100% availability SLA. | Public hosted zone; `A`/`AAAA` alias record → CloudFront distribution | Users, CloudFront |
| **Amazon CloudFront** | CDN for the website and front door for `/api/*` | Serves the React app from edge caches, so the 3,000-student burst never hits the servers. Serving the site straight from the ALB would send every page load into the VPC. | Origin 1: S3 website bucket (Origin Access Control); origin 2: ALB for `/api/*` (no caching, `Authorization` header passed through, secret `X-Origin-Verify` header added); viewers forced to HTTPS (ACM certificate when a custom domain is set); price class 200 (includes India edge locations) | Route 53, WAF, S3 website, ALB |
| **AWS WAF** | Web firewall in front of CloudFront | Blocks SQL injection, XSS and request floods at the edge. Security groups and NACLs only filter by IP and port and can't inspect HTTP requests. | Web ACL on CloudFront: AWS Managed Common Rule Set + Known Bad Inputs; rate limit of 2,000 requests per 5 min per IP | CloudFront |
| **Amazon S3 (website bucket)** | Stores the built React frontend | Static files need no servers. This is cheaper and simpler than running the frontend on EC2 or in a container. | Block all public access; only CloudFront can read (OAC bucket policy); SSE-S3 encryption; versioning on so a bad deploy can be rolled back | CloudFront, GitHub Actions |
| **Amazon Cognito** | Sign-in and role-based access | A managed user pool gives secure password storage, MFA and JWT tokens. Writing our own auth would be slower to build and riskier. | User pool with groups `student`, `tutor`, `admin`; password policy of 12+ characters; optional MFA; JWT access token lifetime 1 h; app client for the React app | Users (browser), API (validates JWT) |

## Network

| Service | Role | Why over an alternative | Configuration | Connects to |
|---|---|---|---|---|
| **Amazon VPC** | Private network for the API and database | Separate public, app and DB subnets keep the database off the internet. Using the default VPC would put everything in public subnets. | `10.0.0.0/16`; public `10.0.1.0/24`, `10.0.2.0/24`; private app `10.0.11.0/24`, `10.0.12.0/24`; private DB `10.0.21.0/24`, `10.0.22.0/24`; spread over 2 AZs | Every service inside it |
| **Internet Gateway** | Internet access for the public subnets | Needed so the ALB can receive traffic and the NAT gateways can reach out. There is no alternative for public subnets. | Attached to the VPC; public route table `0.0.0.0/0 → IGW` | ALB, NAT gateways |
| **NAT Gateway (×2)** | Outbound-only internet for private subnets | Lets API tasks pull images and call AWS APIs without a public IP. One per AZ, so losing an AZ doesn't cut off the other AZ. A single NAT would be cheaper but would be a single point of failure. | One NAT + Elastic IP in each public subnet; app route table A `0.0.0.0/0 → NAT A`, B `→ NAT B`; DB subnets have **no** internet route | API tasks (ECS), Internet Gateway |
| **Security groups** | Firewall for each tier | They're stateful and can reference other groups, so each tier only accepts traffic from the tier before it. That's easier and safer than IP-based NACL rules. | `alb-sg`: port 80 only from the CloudFront managed prefix list; `app-sg`: 8080 from `alb-sg` only; `db-sg`: 5432 from `app-sg` and the marker Lambda's `lambda-sg` only | ALB, ECS, RDS, Lambda |

## API and compute

| Service | Role | Why over an alternative | Configuration | Connects to |
|---|---|---|---|---|
| **Application Load Balancer** | Spreads API requests across tasks in both AZs | Works at HTTP level, with path routing and health checks on `/health`. Removes failed targets within seconds. A Network LB doesn't understand HTTP. | Internet-facing in both public subnets; listener 80 forwards to target group `exam-api` (port 8080, IP targets) **only** if the request carries CloudFront's secret `X-Origin-Verify` header, otherwise 403; health check `/health` every 10 s, 2 failures = unhealthy | CloudFront, ECS tasks |
| **Amazon ECS on Fargate** | Runs the exam API container | No servers to patch or scale. It's simpler than EC2 Auto Scaling, and much less overhead than EKS for one service. | Service `exam-api`, task 0.5 vCPU / 1 GB; normally 2 tasks (1 per AZ), **scheduled scaling** to at least 8 tasks 15 min before exams (so one AZ alone can carry the peak), max 20; target tracking at CPU 60%; deployment circuit breaker with automatic rollback; no public IP; logs to CloudWatch | ALB, RDS, SQS, S3, Secrets Manager, ECR |
| **Amazon ECR** | Stores the API Docker image | Private, in the same AWS account, scanned for vulnerabilities, and pulled using IAM. Docker Hub has rate limits and is public by default. | Private repo `exam-api`; scan on push; immutable tags (git commit SHA); lifecycle rule keeps the last 10 images | GitHub Actions, ECS |

## Data and file storage

| Service | Role | Why over an alternative | Configuration | Connects to |
|---|---|---|---|---|
| **Amazon RDS for PostgreSQL (Multi-AZ)** | Users, exams, questions, attempts, answers and results | The data is relational (results = join of exams + attempts + students). Multi-AZ gives automatic failover with no data loss. DynamoDB makes those joins awkward. Aurora would also work, but costs more at this load (about 100 writes/s). | `db.t4g.medium` in production (`db.t4g.micro` for the demo), PostgreSQL 16; **Multi-AZ** (sync standby in AZ-b); private DB subnets; not publicly accessible; encrypted with KMS; TLS enforced (`rds.force_ssl = 1`, API verifies the RDS certificate); master password managed by RDS in Secrets Manager; automated backups 1 day + point-in-time restore (the AWS Free plan maximum; long-term copies are kept by AWS Backup for 5 years) | ECS API, Lambda auto-marker, Secrets Manager, KMS, AWS Backup |
| **Amazon S3 (submissions bucket)** | Stores assignment files (PDF/ZIP, up to 50 MB) | Cheaper and more durable (11 nines) than EBS or EFS. Presigned URLs keep 50 MB uploads off the API. | Block all public access; **SSE-KMS**; versioning on; **lifecycle**: Standard-IA after 90 days → Glacier Flexible Retrieval after 1 year → delete after 5 years; upload only via **presigned POST** (5-min expiry, content-type PDF/ZIP, `content-length-range` 1 B–50 MB so S3 itself rejects bigger files); CORS allows only the site's origin; HTTPS-only bucket policy; `ObjectCreated` event → notifier Lambda | Students (presigned upload), API, Lambda notifier, KMS |

## Asynchronous processing and email

| Service | Role | Why over an alternative | Configuration | Connects to |
|---|---|---|---|---|
| **Amazon SQS (marking-queue)** | Buffers exam submissions for marking | When 3,000 students submit at once, jobs wait safely in the queue instead of overloading the API. It's simpler than Kinesis, which is built for streams, not jobs. | Standard queue; KMS encrypted; visibility timeout 6 × the Lambda timeout; **dead-letter queue** after 3 failed tries; 4-day retention | ECS API (sends), Lambda auto-marker (consumes) |
| **AWS Lambda – MCQ auto-marker** | Marks MCQ answers and saves scores | Runs only when there is work and scales automatically with the queue. An always-on worker container would cost money while idle. | Python 3.12, 512 MB, 30 s timeout; SQS trigger with batch size 10; attached to the private app subnets (to reach RDS); role allows `sqs:ReceiveMessage/DeleteMessage/GetQueueAttributes` and `secretsmanager:GetSecretValue` | SQS marking-queue, RDS, Secrets Manager |
| **AWS Lambda – notifier** | Emails the tutor when a file is uploaded, and students when results are released | S3 can invoke Lambda directly. Lambda's built-in async queue retries failures, so no server or extra queue is needed. | Python 3.12, 256 MB, 30 s timeout; triggered by S3 `ObjectCreated` (async, 2 retries, failures to an on-failure DLQ); role allows only `ses:SendEmail` + logs | S3 submissions, ECS API (results released), SES |
| **Amazon SES** | Sends the emails | Built for transactional email to any address. SNS email needs each person to confirm a subscription first and can't send personalised messages. | Verified domain `uni.edu` with DKIM/SPF; sender `noreply@uni.edu`; production access (out of sandbox); bounce/complaint notifications | Lambda notifier, tutors, students |

## Security, monitoring and backup

| Service | Role | Why over an alternative | Configuration | Connects to |
|---|---|---|---|---|
| **AWS Secrets Manager** | Stores the database password | Automatic rotation and IAM-controlled access, with no password in code or environment files. SSM Parameter Store has no built-in rotation for RDS. | Database master secret created and **rotated automatically by RDS** (`manage_master_user_password`), encrypted with the KMS key; read only by the ECS task role and the marker Lambda role; the API re-reads it after a failed login, so rotation needs no redeploy | ECS API, Lambda auto-marker, RDS |
| **AWS KMS** | Encryption keys for data at rest | Customer-managed keys allow key policies, yearly rotation and CloudTrail audit of every use. AWS-owned default keys give no control or audit. | Customer-managed keys for RDS, the submissions bucket, SQS and logs; automatic yearly rotation | RDS, S3, SQS, CloudWatch Logs |
| **AWS IAM** | Permissions for every service | Least-privilege roles mean each part can only do its own job. Shared access keys are unsafe and can't be scoped. | ECS task role (S3 put/get on submissions, SQS send, read secret); ECS execution role (ECR pull, write logs); one role per Lambda (above); GitHub OIDC deploy role (no long-lived keys) | ECS, Lambda, GitHub Actions |
| **Amazon CloudWatch** | Logs, metrics and alarms | Built in to every service used here, with no monitoring servers to run. That's simpler than self-hosting Prometheus and Grafana. | Log groups `/exam/ecs/api` and the Lambda groups (90-day retention); alarms on ALB 5xx > 1%, p95 latency > 1 s, SQS oldest message > 60 s, RDS CPU > 80%; alarms email the ops team | ECS, Lambda, ALB, RDS, SQS |
| **AWS Backup** | Keeps database backups for 5 years | RDS automated backups are kept for at most 35 days, but records must be kept for 5 years. AWS Backup gives a central policy with long retention. | Backup plan: daily RDS backup at 02:00 Bhutan time, kept for 5 years (1,825 days); vault encrypted with KMS | RDS, KMS |

## CI/CD

| Service | Role | Why over an alternative | Configuration | Connects to |
|---|---|---|---|---|
| **GitHub Actions** | Pipeline: a push to `main` redeploys automatically | Lives in the same repo, has no server to run, and is free for this use. Jenkins would need its own server, and CodePipeline adds extra setup. | Workflow on push to `main`: unit tests + `terraform validate` → build Lambda packages → build Docker image tagged with the commit SHA → push to ECR → `terraform apply` (new task definition rolls out) → `s3 sync` frontend + CloudFront invalidation → wait until ECS is stable; signs in to AWS with **OIDC** (no stored keys) | GitHub repo, ECR, ECS, S3 website, CloudFront |

## How the services meet the targets

| Target in the brief | Met by |
|---|---|
| 99.9% availability, survives the loss of one AZ | ALB + ECS in 2 AZs, RDS Multi-AZ, NAT per AZ, regional S3/SQS/Lambda/Cognito |
| RPO ≤ 5 min | RDS synchronous standby (RPO ≈ 0); point-in-time restore |
| RTO ≤ 1 h | RDS automatic failover (about 1–2 min); ECS replaces tasks automatically |
| 5-year records | S3 lifecycle (delete after 5 years); AWS Backup 5-year retention |
| Encryption in transit | HTTPS via CloudFront/ALB (ACM), TLS to RDS |
| Encryption at rest | KMS on RDS, S3, SQS and logs |
| Exam peak (3,000 in 5 min) | CloudFront caching, ECS scheduled scaling, presigned uploads, SQS buffering, WAF rate limits |
