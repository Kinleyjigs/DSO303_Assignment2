# Deployment Guide – step by step

Follow these parts in order. Each step shows:
- 💻 the commands to run, copied exactly into your Mac terminal;
- ✅ what you should see;
- 📸 when to take a screenshot. Save each one in `Evidence/` with the name given.

Everything you create in AWS is named `yonten-…`, so it can't clash with the other deployment in this shared account (`363242104805`).

| Part | What happens | Time |
|---|---|---|
| A | Get the latest project into your folder | 2 min |
| B | Sign your Mac in to AWS | 3 min |
| C | Bootstrap: state bucket + GitHub deploy role | 2 min |
| D | Give GitHub the 4 settings it needs | 3 min |
| E | Push → GitHub builds the whole platform | 20–25 min |
| F | Confirm the two AWS emails | 1 min |
| G | Create a student and a tutor login | 2 min |
| H | Test walkthrough 1 on the live site | 5 min |
| I | Test walkthrough 2 on the live site | 5 min |
| J | Show two AZs, encryption and lifecycle in the console | 5 min |
| K | Show that a push to `main` redeploys automatically | 10 min |
| L | **Tear down** (stops the cost) | 15 min |

> 💰 The platform costs about **US$4–6 per day** while it runs. Do parts E to L in one sitting if you can, and **always finish with Part L**.

---

## Part A – Get the latest project

1. Download `DSO303_Assignment2-full.zip` from the chat into **Downloads**.
2. 💻 Run:

```bash
cd ~/path/to/DSO303_Assignment2          # your project folder

# remove leftovers from the failed bootstrap and the duplicate Lab files
rm -rf bootstrap/.terraform bootstrap/terraform.tfstate bootstrap/terraform.tfstate.backup bootstrap/.terraform.lock.hcl
rm -f Architecture_Design/assignment2-upload.json Architecture_Design/assignment2-w1.json

# copy in the latest project (your Evidence/ screenshots are not touched)
cd ..
unzip -o ~/Downloads/DSO303_Assignment2-full.zip
cd DSO303_Assignment2

# check
ls -a
ls Architecture_Design
grep -n 'default     = "yonten"' bootstrap/main.tf infra/variables.tf
```

✅ You should see:
- `.github`, `pytest.ini` and `DEPLOY_GUIDE.md` in the list;
- `README.md`, `architecture.png`, `diagram.py` and two walkthrough PNGs in `Architecture_Design`;
- two lines ending in `"yonten"`.

---

## Part B – Sign your Mac in to AWS

Skip this part if `aws sts get-caller-identity` already shows `user/YontenKT`.

1. In the AWS website, go to **IAM → Users → YontenKT → Security credentials**.
2. **Delete the old key** you pasted in the chat earlier (`AKIAVJEXKU7SX563D2DT`): **Actions → Deactivate**, then **Delete**.
3. Click **Create access key**, choose **Command Line Interface (CLI)**, tick the box, then click **Next** and **Create access key**.
4. 💻 Run:

```bash
aws configure
```

Answer the questions like this:

```
AWS Access Key ID:      <new Access key ID>
AWS Secret Access Key:  <new Secret access key>
Default region name:    us-east-1
Default output format:  json
```

5. 💻 Test it:

```bash
aws sts get-caller-identity
```

✅ The output shows `"Arn": "arn:aws:iam::363242104805:user/YontenKT"`.

> 🔒 Never paste the secret key into a chat, a file in the repo, or a screenshot.

---

## Part C – Bootstrap (one time only)

This creates your **Terraform state bucket** and a **deploy role** that only your GitHub repo's `main` branch can use.

💻 Run:

```bash
cd bootstrap
terraform init
terraform apply -var github_repo=Kinleyjigs/DSO303_Assignment2
```

Terraform shows a plan ending in **`Plan: 5 to add, 0 to change, 0 to destroy.`** Type **`yes`** and press Enter.

✅ The end of the output:

```
Apply complete! Resources: 5 added, 0 changed, 0 destroyed.

Outputs:
deploy_role_arn = "arn:aws:iam::363242104805:role/yonten-github-deploy"
state_bucket    = "yonten-tfstate-363242104805"
```

📸 **`Evidence/09-bootstrap.png`**: the `Apply complete!` part with both outputs.

💻 Go back to the project folder:

```bash
cd ..
```

---

## Part D – Give GitHub the settings it needs

1. Open `https://github.com/Kinleyjigs/DSO303_Assignment2`.
2. Go to **Settings → Secrets and variables → Actions → Variables tab → New repository variable**.
3. Add these four, one at a time:

| Name | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | `arn:aws:iam::363242104805:role/yonten-github-deploy` |
| `TF_STATE_BUCKET` | `yonten-tfstate-363242104805` |
| `SENDER_EMAIL` | An email you can open, e.g. your Gmail |
| `TUTOR_EMAIL` | The same email again, or a second one you can open |

Optionally, add `ALERT_EMAIL`, an email for CloudWatch alarms.

> Use the **Variables** tab, not Secrets. None of these values are secret.

📸 **`Evidence/10-github-variables.png`**: the Variables list. It shows names and values, with nothing sensitive.

---

## Part E – Push → GitHub builds everything

💻 Run:

```bash
git add -A
git commit -m "Assignment 2: full project with yonten prefix and deploy guide"
git push
```

Then:
1. On GitHub, open the **Actions** tab and click the newest **test-and-deploy** run.
2. The **test** job runs first, in about 2 minutes. Then **deploy** runs, which takes **20–25 minutes** the first time. RDS Multi-AZ and CloudFront are the slow parts.

✅ Both jobs show a green tick ✓. At the bottom of the run page, the **Summary** shows:

```
Site: https://dxxxxxxxxxxxx.cloudfront.net
```

Copy this URL. You'll open it in Parts H and I.

📸 **`Evidence/11-pipeline-green.png`**: the run with both jobs green and the Site URL visible.

**If a job turns red ❌,** click the failed step, screenshot the red error lines, and send them to me. See also the *Troubleshooting* section at the end.

---

## Part F – Confirm the two AWS emails

While the pipeline runs, AWS SES emails `SENDER_EMAIL` and `TUTOR_EMAIL` with the subject **"Amazon Web Services – Email Address Verification Request"**.

**Open both emails and click the link in each.** Until you do, the platform can't send any emails. Check your spam folder if you don't see them.

✅ The link opens a page that says **"Congratulations! You've successfully verified an email address."**

---

## Part G – Create a student and a tutor login

💻 Run this from the project folder, **after** the pipeline is green. The init command connects your terminal to the state that GitHub created:

```bash
terraform -chdir=infra init -backend-config="bucket=yonten-tfstate-363242104805"

./scripts/create_user.sh  <your-email-1>  'Student12345A'  student
./scripts/create_user.sh  <your-email-2>  'Tutor123456A'   tutor
```

- Use real addresses you can open. They can be the same two you used in Part D.
- Passwords need **12+ characters with uppercase, lowercase and a number**. Choose your own and remember them.

✅ Each command prints `Created <email> as student` or `Created <email> as tutor`.

---

## Part H – Walkthrough 1 on the live site (exam + autosave)

1. Open the **Site URL** from Part E in Chrome.
2. Sign in with the **student** email and password.
3. Next to **DSO303 Demo Exam**, click **Start / resume**.
4. Open DevTools (**⌥⌘I**) and go to the **Network** tab.
5. Answer the 3 questions, then wait **30 seconds**. The status changes to **"Autosave: saved hh:mm:ss"**, and the Network tab shows a **`answers`** request with status **200**.

📸 **`Evidence/12-w1-exam-autosave.png`**: the exam page showing "saved …" **and** the Network tab with the `PUT …/answers` row and its 200 status.

6. Click **Submit exam**. The message reads *"Submitted. MCQs are being marked."*
7. In the AWS console, go to **CloudWatch → Log groups → `/aws/lambda/yonten-marker`**, open the newest log stream, and find the line `{"attempt_id": 1, "mcq_score": …}`.

📸 **`Evidence/13-w1-marker-log.png`**: that log line. It proves the SQS → Lambda marking works.

---

## Part I – Walkthrough 2 on the live site (40 MB upload, tutor notified)

1. On the same page, scroll to **Assignment upload**.
2. Choose a **PDF** of about **40 MB**. If you don't have one, make one with:

```bash
mkfile -n 40m ~/Desktop/assignment-40mb.pdf
```

   This file isn't a real PDF, but its name and size are enough for the test.

3. Click **Upload**.

✅ The page shows **"Uploaded. Your tutor has been notified."**

📸 **`Evidence/14-w2-upload-page.png`**: the success message.

4. In the AWS console, go to **S3 → `yonten-submissions-363242104805` → `submissions/1/…`** and click the file. In its properties, **Server-side encryption** shows **AWS-KMS**.

📸 **`Evidence/15-w2-s3-object.png`**: the object, showing its 40 MB size and KMS encryption.

5. Open the **tutor's inbox**. You'll find an email titled **"New submission for assignment 1"**.

📸 **`Evidence/16-w2-tutor-email.png`**: the email.

6. Optionally, go to **CloudWatch → Log groups → `/aws/lambda/yonten-notifier`** and find `{'emails_sent': 1}`.

**Optional: results email.** Sign out, sign in as the **tutor**, and click **Release results**. The student's inbox gets "Results released".

---

## Part J – Show two AZs, encryption and lifecycle in the console

Take these screenshots in the AWS console:

| 📸 File | Where | What must be visible |
|---|---|---|
| `Evidence/17-rds-multi-az.png` | **RDS → Databases → `yonten-db`** | *Multi-AZ: Yes*, *Encryption: Enabled*, and the primary and secondary AZ |
| `Evidence/18-ecs-two-azs.png` | **ECS → Clusters → `yonten-cluster` → Services → `yonten-api` → Tasks** | 2 running tasks in **different** AZs (e.g. us-east-1a and us-east-1b) |
| `Evidence/19-s3-lifecycle.png` | **S3 → `yonten-submissions-…` → Management** | The `keep-5-years` rule: 90 days → Standard-IA, 365 → Glacier, 1,825 → expire |
| `Evidence/20-vpc-subnets.png` | **VPC → Subnets**, filtered by `yonten` | 6 subnets: public, app and db, in two AZs |

---

## Part K – Show that a push to `main` redeploys automatically

1. Make a small visible change. For example, in `frontend/index.html`, change:

```html
<h1>Online Exam Platform</h1>
```

   to:

```html
<h1>Online Exam Platform – CST</h1>
```

2. 💻 Push it:

```bash
git add -A
git commit -m "Change page title to show automatic redeploy"
git push
```

3. On GitHub, open **Actions**. A new run starts by itself. This one takes about 5 minutes.
4. When it's green, refresh the site. The new title appears. You may need **⌘⇧R** to bypass the cache.

📸 **`Evidence/21-redeploy-run.png`**: the second green run.
📸 **`Evidence/22-redeploy-site.png`**: the site showing the new title.

---

## Part L – Tear down (do not skip)

💻 Run from the project folder:

```bash
terraform -chdir=infra init -backend-config="bucket=yonten-tfstate-363242104805"
./scripts/destroy.sh -var sender_email=<SENDER_EMAIL> -var tutor_email=<TUTOR_EMAIL>
```

Use the same two emails as in Part D. It takes about **15 minutes**, mostly deleting CloudFront and RDS.

✅ The end of the output:

```
Destroy complete! Resources: … destroyed.
```

📸 **`Evidence/23-destroy-complete.png`**

Then remove the bootstrap as well, after you've finished pushing to GitHub for this assignment:

```bash
cd bootstrap
terraform destroy -var github_repo=Kinleyjigs/DSO303_Assignment2
cd ..
```

Finally, in **IAM → YontenKT → Security credentials**, deactivate and delete the access key you created in Part B.

✅ Everything named `yonten-…` is gone, and **nothing else in the account was touched**.

---

## After the deployment: add the screenshots to the report

Open the root `README.md` and add this section above **"Design notes"**:

```markdown
## Deployment evidence

| What | Screenshot |
|---|---|
| Bootstrap (state bucket + OIDC deploy role) | ![](Evidence/09-bootstrap.png) |
| Pipeline green after push to main | ![](Evidence/11-pipeline-green.png) |
| Walkthrough 1: autosave (PUT 200) | ![](Evidence/12-w1-exam-autosave.png) |
| Walkthrough 1: MCQ marked by Lambda | ![](Evidence/13-w1-marker-log.png) |
| Walkthrough 2: upload succeeded | ![](Evidence/14-w2-upload-page.png) |
| Walkthrough 2: file in S3 (KMS encrypted) | ![](Evidence/15-w2-s3-object.png) |
| Walkthrough 2: tutor email | ![](Evidence/16-w2-tutor-email.png) |
| RDS Multi-AZ | ![](Evidence/17-rds-multi-az.png) |
| ECS tasks in two AZs | ![](Evidence/18-ecs-two-azs.png) |
| S3 lifecycle (5 years) | ![](Evidence/19-s3-lifecycle.png) |
| Six subnets over two AZs | ![](Evidence/20-vpc-subnets.png) |
| Push to main redeploys | ![](Evidence/21-redeploy-run.png) ![](Evidence/22-redeploy-site.png) |
| Tear-down | ![](Evidence/23-destroy-complete.png) |
```

Then:

```bash
git add -A
git commit -m "Add deployment evidence"
git push
```

Pushing after Part L will start the pipeline again and **redeploy everything**. To avoid this, either push the evidence **before** Part L, or after tear-down disable the workflow first: **Actions → test-and-deploy → ⋯ → Disable workflow**.

---

## Troubleshooting

| Error | Fix |
|---|---|
| `No valid credential sources found` / `Unable to locate credentials` | Your terminal isn't signed in to AWS. Redo Part B. |
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` (GitHub deploy job) | The repo name in Part C doesn't match GitHub exactly (it's case-sensitive), or the push wasn't to `main`. Rerun Part C with the exact name. |
| `BucketAlreadyExists` / `EntityAlreadyExists` | A name clashes with someone else's resource. Send me the error. |
| Pipeline red at **Terraform format + validate** | Screenshot the red lines and send them to me. |
| Sign-in says `Incorrect username or password` | Rerun the `create_user.sh` line from Part G. The password needs 12+ characters with upper case, lower case and a number. |
| Page loads but says `Please sign in again` repeatedly | Wait 2–3 minutes after the first deploy for the API to be ready, then refresh. |
| Upload works but no email | You didn't click the SES verification links in Part F. Click them, then upload again. |
| `destroy` stops on the backup vault | A backup job is running. Wait 5 minutes and run the destroy command again. |
| Anything else | Screenshot the error and send it to me, together with the Part letter you were on. |
