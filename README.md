## Deployment evidence (real AWS, us-east-1)

| What it proves | Screenshot |
|---|---|
| Bootstrap: state bucket + GitHub OIDC deploy role | ![](Evidence/09-bootstrap.png) |
| GitHub repository variables | ![](Evidence/10-github-variables.png) |
| Pipeline green after push to `main` | ![](Evidence/11-pipeline-green.png) |
| **Walkthrough 1:** autosave every 30 s (`PUT …/answers` → 200) | ![](Evidence/12-w1-exam-autosave.png) |
| Walkthrough 1: answers locked after submit (server rule) | ![](Evidence/12b-w1-locked-after-submit.png) |
| Walkthrough 1: marking failed, job kept in the dead-letter queue | ![](Evidence/13a-marker-error-before-fix.png) |
| Walkthrough 1: after the fix and redrive, MCQs marked by Lambda | ![](Evidence/13-w1-marker-log.png) |
| **Walkthrough 2:** upload rejected before the SigV4 fix (KMS bucket) | ![](Evidence/14a-w2-upload-rejected-before-fix.png) |
| Walkthrough 2: upload succeeded | ![](Evidence/14-w2-upload-page.png) |
| Walkthrough 2: file stored in S3 | ![](Evidence/15-w2-s3-object.png) |
| Walkthrough 2: file encrypted with KMS | ![](Evidence/15b-w2-s3-kms.png) |
| Walkthrough 2: SES refused unverified addresses (sandbox rule) | ![](Evidence/16b-w2-ses-not-verified.png) |
| Walkthrough 2: notifier Lambda sent the email | ![](Evidence/16a-w2-notifier-log.png) |
| Walkthrough 2: tutor received "New submission" email | ![](Evidence/16-w2-tutor-email.png) |
| RDS Multi-AZ + encryption | ![](Evidence/17-rds-multi-az.png) |
| ECS tasks running in two AZs | ![](Evidence/18-ecs-two-azs.png) |
| S3 lifecycle: IA 90 d → Glacier 1 y → delete 5 y | ![](Evidence/19-s3-lifecycle.png) |
| Six subnets across two AZs | ![](Evidence/20-vpc-subnets.png) |
| Every push to `main` redeployed automatically | ![](Evidence/21-redeploy-runs.png) |

### Problems found during deployment and how they were fixed

| Problem | Cause | Fix |
|---|---|---|
| GitHub could not assume the AWS role | GitHub now sends an ID-based OIDC subject (`repo:owner@id/repo@id:…`) | Role trust accepts both subject formats, still limited to this repo's `main` branch |
| RDS creation refused | AWS Free plan allows at most 1 day of automated backups | 1-day backups; 5-year retention kept by AWS Backup |
| MCQ marker crashed | `scramp` 1.5.0 removed a function `pg8000` needs | Pinned `scramp==1.4.18`; failed jobs redriven from the DLQ, so no submission was lost |
| Upload rejected by S3 (400) | KMS-encrypted buckets require Signature Version 4 | Presigned POST now signed with SigV4 |
| Tutor email not sent | SES sandbox only sends between verified addresses | Verified sender and tutor addresses |