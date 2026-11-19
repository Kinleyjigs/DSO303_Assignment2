# Task 1: Architecture Design

## 1. The design in one paragraph

Students and tutors open the site through **Route 53** (DNS) and **CloudFront** (CDN), with **WAF** blocking bad traffic. The website is a React app stored in **S3**, and users sign in with **Cognito**. All API calls go to a **load balancer** in the public subnets. The load balancer sends them to the **API running on ECS Fargate** in private subnets, and the API stores everything in an **RDS PostgreSQL** database. The database keeps a primary copy in one Availability Zone and a standby in the other. Assignment files go straight from the browser into an **S3 bucket**. Slow background jobs run in **Lambda** functions:

- Exam marking goes through an **SQS queue**.
- Uploads trigger an email Lambda directly, and emails are sent with **SES**.

Everything runs in **two Availability Zones**, so the platform keeps working if one fails.

### Architecture diagram

![Architecture diagram](architecture.png)

### Built in the Cloud Architecture Lab

![Full Lab canvas](../Evidence/01-full-canvas.png)

## 2. Components (what each layer is for)

| Layer | Services | What it does |
|---|---|---|
| Edge | Route 53, CloudFront, WAF | DNS name, fast global delivery over HTTPS, blocks attacks and floods |
| Frontend | S3 (website bucket) | Holds the React app; only CloudFront can read it |
| Authentication | Cognito | Sign-in with three roles: student, tutor and admin |
| Network | VPC with public, private-app and private-DB subnets in AZ-a and AZ-b; internet gateway; one NAT gateway per AZ | Only the load balancer is public. The API and the database have no public IP. |
| API / compute | Application Load Balancer, ECS Fargate (tasks in both AZs) | Runs the exam API and scales up before exams |
| Database | RDS PostgreSQL Multi-AZ (primary + standby) | Users, exams, answers and results. Every write is copied instantly to the standby. |
| File storage | S3 submissions bucket | Encrypted. Lifecycle rules move files to Standard-IA after 90 days and Glacier after 1 year, and delete them after 5 years. |
| Async processing | SQS marking-queue → Lambda auto-marker; S3 upload event → Lambda notifier → SES | Marks MCQs and sends emails without slowing the API |
| Security | Security groups, Secrets Manager, KMS | Each tier only accepts traffic from the tier in front of it. The DB password is kept in Secrets Manager. All data is encrypted. |
| Monitoring and backup | CloudWatch, AWS Backup | Logs and alarms; database backups kept for 5 years |
| CI/CD | GitHub Actions, ECR | A push to `main` tests, builds and redeploys automatically |

**Security groups chain each tier:**

| Security group | Allows |
|---|---|
| `alb-sg` | Port 80 from CloudFront only (users always connect to CloudFront over HTTPS) |
| `app-sg` | Port 8080 from `alb-sg` only |
| `db-sg` | Port 5432 from `app-sg` (and the marker Lambda) only |

## 3. Walkthrough 1: A student opens an exam and answers autosave

![Walkthrough 1 diagram](walkthrough-1-exam-autosave.png)

1. **Sign in.** The student signs in with **Cognito** and gets a token with the role *student*. Every API call carries this token.
2. **Load the app.** The browser opens `exams.uni.edu`. **Route 53** points it to **CloudFront**, and **WAF** checks the request. CloudFront serves the React app from the private S3 website bucket over HTTPS.
3. **Open the exam.** The browser sends `POST /api/exams/{id}/start`, and CloudFront forwards `/api/*` requests to the **load balancer**.
4. **API checks.** The load balancer passes the request to a healthy **API task (ECS)** in a private subnet. The API:
   - checks the token and the *student* role;
   - checks that the exam is open;
   - records the start time on the server, so the timer can't be changed in the browser;
   - returns the questions **without** the answer key.
5. **Autosave every 30 seconds.** The browser sends `PUT /api/attempts/{id}/answers` with the changed answers. The API saves them in **RDS**. A repeated save overwrites the same row, so there are no duplicates. The DB password comes from **Secrets Manager**.
6. **No lost answers.** RDS **instantly copies** each save to the standby in the other AZ, so a saved answer survives even if AZ-a fails.
7. **Submit and mark.** When the student submits, or time runs out, the API adds a job to the **SQS marking-queue**, and a **Lambda** marks the MCQs. Short answers wait for the tutor.

**Simulation in the Cloud Architecture Lab:** the request passes Route 53 → CloudFront → Load balancer → API (ECS) → RDS and completes with HTTP 200.

![Walkthrough 1 – Lab canvas](../Evidence/03-w1-canvas.png)

![Walkthrough 1 – decision trace (SUCCESS)](../Evidence/02-w1-trace.png)

## 4. Walkthrough 2: A student uploads a 40 MB assignment and the tutor is notified

![Walkthrough 2 diagram](walkthrough-2-upload-notify.png)

1. **Ask to upload.** The student asks the **API** to upload a 40 MB PDF: `POST /api/assignments/{id}/upload-url`.
2. **API checks.** The API checks the role, the deadline, the file type (PDF or ZIP) and the size (50 MB or less). It returns a **presigned upload link** that is valid for 5 minutes and only accepts that file type, up to 50 MB.
3. **Upload directly to S3.** The browser uploads the file **straight to the S3 submissions bucket**, so the large file never goes through the load balancer or the API. S3 encrypts the file with **KMS**, keeps versions, and blocks all public access.
4. **Event.** S3 sends a "file uploaded" event that triggers the **notifier Lambda**. S3 invokes it asynchronously, so Lambda queues the event internally and retries it twice if it fails.
5. **Email.** The Lambda asks **SES** to send an email.
6. **Tutor notified.** The **tutor** receives a "new submission" email.
7. **Retention.** Lifecycle rules move the file to cheaper storage after 90 days and 1 year, then delete it after **5 years**.

**Simulation in the Cloud Architecture Lab:** the upload passes Student → S3 → Lambda notifier and completes successfully (5 steps). The Lab does not model email delivery to a person, so Lambda → SES → Tutor is shown as a dependency on the canvas, not as an animated step.

![Walkthrough 2 – Lab canvas](../Evidence/05-w2-canvas.png)

![Walkthrough 2 – decision trace (SUCCESS)](../Evidence/04-w2-trace.png)

## 5. How the design handles the exam peak and the loss of one AZ

**Exam peak.** 3,000 students starting within 5 minutes is about 10 sign-ins per second. Autosave then adds about 100 small database writes per second (3,000 students ÷ 30 s). CloudFront serves the website from its cache, so page loads never reach the servers. ECS **scheduled scaling** adds API tasks 15 minutes before each exam, and auto-scaling adds more if CPU goes above 60%. Uploads go straight to S3 through presigned links, so big files don't slow the API. Exam submissions go into the SQS marking-queue, so a burst just waits while Lambda works through it. Upload emails use Lambda's own asynchronous event queue, which also retries. WAF rate limits stop any single client from flooding the system, and CloudWatch alarms warn the team if errors or delays rise.

**Loss of one Availability Zone.** Every tier runs in both AZs. If AZ-a fails, the load balancer's health checks stop sending traffic there within seconds, and the API tasks in AZ-b take over. The service is sized so **one AZ alone can handle the peak**, and ECS starts replacement tasks. RDS Multi-AZ automatically promotes the standby in AZ-b to primary in about 1–2 minutes. Every save was already copied, so **no answers are lost**: the RPO is about 0 against the 5-minute target, and the RTO is a few minutes against the 1-hour target. Each AZ has its own NAT gateway, and S3, SQS, Lambda, Cognito, SES and CloudFront are regional services that keep running. AWS Backup and point-in-time restore cover data corruption.
