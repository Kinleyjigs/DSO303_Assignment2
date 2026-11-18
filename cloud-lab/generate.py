"""
Assignment 2 - Cloud Architecture Lab workspace (simplified: only what the brief requires).
python generate.py  ->  assignment2.json   (Lab: Export > Upload JSON)

Walkthrough 1: start node "Student - exam"   (Student > Route 53 > CloudFront > ALB > ECS > RDS)
Walkthrough 2: start node "Student - upload" (Student > S3 > Lambda; Lambda > SES > Tutor shown as dependency)
AZ failure:    fail ALB (AZ-a), ECS (AZ-a), RDS primary, then rerun walkthrough 1
"""
import ipaddress, json

# ---------- helpers (same shapes as the Lab's own exports) ----------
def subnet_meta(cidr):
    a = list(ipaddress.ip_network(cidr))
    roles = [("Network Address", "First address in the subnet. Identifies the network itself."),
             ("VPC Router", "Reserved by AWS for the default VPC router / subnet gateway."),
             ("Amazon-Provided DNS", "Reserved by AWS for the DNS resolver (Route 53 Resolver / AmazonProvidedDNS)."),
             ("AWS Future Use", "Reserved by AWS for potential future internal functionality.")]
    res = [{"ip": str(a[i]), "offset": i, "role": r, "description": d} for i, (r, d) in enumerate(roles)]
    res.append({"ip": str(a[-1]), "offset": len(a) - 1, "role": "Network Broadcast Address",
                "description": "Last address in the subnet. AWS does not support broadcast in a VPC, but reserves the address."})
    return {"cidr": cidr, "totalAddresses": len(a), "usableHosts": len(a) - 5, "reservedAddresses": res,
            "usableRange": {"start": str(a[4]), "end": str(a[-2])}}

def box(id, label, btype, x, y, w, h, z, **extra):
    return {"id": id, "type": "boundaryNode", "position": {"x": x, "y": y},
            "data": {"label": label, "boundaryType": btype, "width": w, "height": h, **extra},
            "style": {"width": w, "height": h}, "draggable": True, "selectable": True, "zIndex": z,
            "measured": {"width": w, "height": h}, "selected": False}

def subnet(id, label, btype, cidr, az, rt, x, y):
    return box(id, label, btype, x, y, 560, 210, -3, **subnet_meta(cidr), az=az, routeTable=rt)

def sg(id, label, x, y, w, inbound=None, protocols=None):
    extra = {}
    if protocols: extra["allowedProtocols"] = protocols
    if inbound is not None: extra["securityGroupRules"] = {"inbound": inbound, "outbound": []}
    return box(id, label, "security_group", x, y, w, 160, -2, **extra)

def rule(proto, port, src):
    return {"protocol": proto, "portRange": str(port), "source": {"type": "securityGroup", "securityGroupId": src}}

def svc(id, sid, label, cat, x, y, az="Edge / Global", sub="global", sgs=None, multi=False, cfg=None, notes=None):
    d = {"serviceId": sid, "label": label, "category": cat, "health": "healthy", "az": az, "subnet": sub,
         "replicas": 1, "multiAz": multi, "width": 140, "height": 98}
    if sgs: d["securityGroupIds"] = sgs
    if cfg: d["customConfig"] = cfg
    if notes: d["notes"] = notes
    return {"id": id, "type": "serviceNode", "position": {"x": x, "y": y}, "data": d, "zIndex": 10,
            "measured": {"width": 140, "height": 98}, "style": {"width": 140, "height": 98}}

def edge(src, dst, desc, rel="request", proto="HTTPS", port=None, critical=True):
    d = {"relationship": rel, "protocol": proto, "transport": proto, "lineStyle": "straight",
         "interactionType": "synchronous", "isCriticalDependency": critical, "timeoutMs": 2500,
         "isFailing": False, "description": desc}
    if port: d["destinationPort"] = port
    if proto == "SQL":      # database calls = dependency calls (the shape that passed in W1)
        d.pop("transport"); d["relationship"] = "dependency"; d["traversal"] = "dependency"
        d["dependencyRequired"] = critical
    return {"zIndex": 1000, "source": src, "sourceHandle": "source-right", "target": dst,
            "targetHandle": "target-left", "id": f"edge-{src}-{dst}", "type": "custom",
            "markerEnd": {"type": "arrowclosed", "color": "#94A3B8"}, "data": d}

def dep(src, dst, desc, proto="HTTPS", port=None):
    return edge(src, dst, desc, rel="dependency", proto=proto, port=port, critical=False)


SQS_CONSUME = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
def lambda_cfg(role, queue_arn, extra_actions, vpc=None):
    """Execution role written in several common shapes so the simulator finds the permissions."""
    stmt = [{"Effect": "Allow", "Action": SQS_CONSUME, "Resource": queue_arn},
            {"Effect": "Allow", "Action": extra_actions, "Resource": "*"},
            {"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"], "Resource": "*"}]
    actions = SQS_CONSUME + extra_actions + ["logs:CreateLogStream", "logs:PutLogEvents"]
    cfg = {"runtime": "python3.12",
           "executionRole": {"name": role, "trust": "lambda.amazonaws.com", "actions": actions,
                             "policy": {"Version": "2012-10-17", "Statement": stmt}},
           "role": f"arn:aws:iam::000000000000:role/{role}",
           "iamPermissions": actions, "permissions": actions,
           "eventSourceMapping": {"source": queue_arn, "batchSize": 10, "enabled": True},
           "lambdaWorkspace": {"functionName": role.replace("-role", ""), "runtime": "python3.12",
                               "executionRole": f"arn:aws:iam::000000000000:role/{role}",
                               "roleName": role, "permissions": actions,
                               "eventSources": [{"type": "sqs", "arn": queue_arn, "batchSize": 10}]}}
    if vpc: cfg["vpc"] = vpc
    return cfg

NET, CMP, DB, STO, SEC, INT, MGT, CLI = ("Networking & Content Delivery", "Compute", "Databases", "Storage",
    "Security, Identity & Compliance", "Integration & Messaging", "Management & Governance", "Client / Ingress")

# ---------- network boundaries ----------
PUB = "exam-public-rt (0.0.0.0/0 -> exam-igw)"
APP_A = "exam-app-rt-a (0.0.0.0/0 -> NAT A)"
APP_B = "exam-app-rt-b (0.0.0.0/0 -> NAT B)"
DBRT = "exam-db-rt (local only - no internet)"
nodes = [
    box("vpc", "exam-vpc 10.0.0.0/16", "vpc", 0, 0, 1200, 900, -4, cidr="10.0.0.0/16"),
    subnet("sn-pub-a", "Public subnet A (us-east-1a)", "public_subnet", "10.0.1.0/24", "AZ-A", PUB, 30, 40),
    subnet("sn-pub-b", "Public subnet B (us-east-1b)", "public_subnet", "10.0.2.0/24", "AZ-B", PUB, 610, 40),
    subnet("sn-app-a", "Private app subnet A (us-east-1a)", "private_subnet", "10.0.11.0/24", "AZ-A", APP_A, 30, 290),
    subnet("sn-app-b", "Private app subnet B (us-east-1b)", "private_subnet", "10.0.12.0/24", "AZ-B", APP_B, 610, 290),
    subnet("sn-db-a", "Private DB subnet A (us-east-1a)", "private_subnet", "10.0.21.0/24", "AZ-A", DBRT, 30, 540),
    subnet("sn-db-b", "Private DB subnet B (us-east-1b)", "private_subnet", "10.0.22.0/24", "AZ-B", DBRT, 610, 540),
    sg("sg-alb", "alb-sg: 443 from internet", 50, 75, 190, protocols=["HTTP", "HTTPS"]),
    sg("sg-alb-b", "alb-sg: 443 from internet", 630, 75, 190, protocols=["HTTP", "HTTPS"]),
    sg("sg-app", "app-sg: 8080 from alb-sg", 50, 325, 190, inbound=[rule("HTTP", 8080, "sg-alb")]),
    sg("sg-app-b", "app-sg: 8080 from alb-sg", 630, 325, 190, inbound=[rule("HTTP", 8080, "sg-alb")]),
    sg("sg-db", "db-sg: 5432 from app-sg", 50, 575, 190, inbound=[rule("SQL", 5432, "sg-app")]),
    sg("sg-db-b", "db-sg: 5432 from app-sg", 630, 575, 190, inbound=[rule("SQL", 5432, "sg-app")]),
]

ecs = lambda az: {"cluster": "exam-cluster", "service": "exam-api", "launchType": "FARGATE", "cpu": "512",
                  "memory": "1024", "containerPort": 8080, "image": "ECR exam-api:latest",
                  "desiredCount": "2 per AZ (4 total)", "autoScaling": "4-20 tasks; scale up 15 min before each exam; CPU target 60%",
                  "assignPublicIp": "DISABLED", "az": az}
rds = {"engine": "PostgreSQL 16", "class": "db.t4g.medium", "multiAz": True, "encrypted": "KMS",
       "backupRetentionDays": 7, "pointInTimeRestore": True, "publiclyAccessible": False}

nodes += [
    # people
    svc("node-student", "user", "Student - exam (start W1)", CLI, -680, 140),
    svc("node-student-upload", "user", "Student - upload (start W2)", CLI, -680, 1000),
    svc("node-tutor", "user", "Tutor (gets email)", CLI, 1000, 1000),
    # edge + frontend + auth
    svc("node-route53", "route53", "Route 53 (exams.uni.edu)", NET, -450, 140),
    svc("node-cloudfront", "cloudfront", "CloudFront (CDN, HTTPS)", NET, -220, 140),
    svc("node-waf", "waf", "AWS WAF (on CloudFront)", SEC, -220, -40,
        cfg={"rules": ["AWS managed common rules", "rate limit per IP"]}),
    svc("node-s3-web", "s3", "S3 website bucket (React app)", STO, -220, 330, cfg={"publicAccess": "blocked (CloudFront OAC only)"}),
    svc("node-cognito", "cognito", "Cognito (student / tutor / admin)", SEC, -450, 330),
    # VPC
    svc("node-alb-a", "alb", "Load balancer (AZ-a)", NET, 70, 105, "AZ-A", "public", ["sg-alb"], True),
    svc("node-alb-b", "alb", "Load balancer (AZ-b)", NET, 650, 105, "AZ-B", "public", ["sg-alb-b"], True),
    svc("node-nat-a", "nat_gateway", "NAT gateway A", NET, 400, 105, "AZ-A", "public"),
    svc("node-nat-b", "nat_gateway", "NAT gateway B", NET, 980, 105, "AZ-B", "public"),
    svc("node-ecs-a", "ecs", "API on ECS Fargate (AZ-a)", CMP, 70, 355, "AZ-A", "private", ["sg-app"], cfg=ecs("us-east-1a")),
    svc("node-ecs-b", "ecs", "API on ECS Fargate (AZ-b)", CMP, 650, 355, "AZ-B", "private", ["sg-app-b"], cfg=ecs("us-east-1b")),
    svc("node-rds-a", "rds", "RDS PostgreSQL PRIMARY (AZ-a)", DB, 70, 605, "AZ-A", "private", ["sg-db"], True, rds),
    svc("node-rds-b", "rds", "RDS PostgreSQL STANDBY (AZ-b)", DB, 650, 605, "AZ-B", "private", ["sg-db-b"], True, rds,
        notes="Multi-AZ standby: every write is copied here instantly; takes over automatically if AZ-a fails."),
    svc("node-igw", "internet_gateway", "Internet gateway", NET, 530, 790),
    # files + async (row below the VPC)
    svc("node-s3-files", "s3", "S3 submissions bucket (lifecycle 5 years)", STO, -220, 1000,
        cfg={"encryption": "SSE-KMS", "versioning": True, "publicAccess": "blocked", "maxUpload": "50 MB (presigned URL)",
             "lifecycle": ["Standard-IA after 90 days", "Glacier after 1 year", "delete after 5 years"]}),
    svc("node-lambda-notify", "lambda", "Lambda notifier", CMP, 230, 1000, multi=True,
        cfg={"runtime": "python3.12", "trigger": "S3 ObjectCreated event on exam-submissions (asynchronous invoke)",
             "resourcePolicy": "allow s3.amazonaws.com to lambda:InvokeFunction (source: exam-submissions bucket)",
             "asyncRetries": 2, "onFailureDestination": "SQS notify-dlq",
             "executionRole": {"name": "exam-notifier-role", "trust": "lambda.amazonaws.com",
                               "actions": ["ses:SendEmail", "ses:SendRawEmail", "logs:CreateLogStream", "logs:PutLogEvents"]},
             "iamPermissions": ["ses:SendEmail", "ses:SendRawEmail"], "permissions": ["ses:SendEmail", "ses:SendRawEmail"]}),
    svc("node-ses", "ses", "Amazon SES (email)", "Business Applications", 680, 1000),
    svc("node-sqs-mark", "sqs", "SQS marking-queue (+ dead-letter queue)", INT, 80, 1180),
    svc("node-lambda-mark", "lambda", "Lambda MCQ auto-marker", CMP, 380, 1180, multi=True,
        cfg=lambda_cfg("exam-marker-role", "arn:aws:sqs:us-east-1:000000000000:marking-queue",
                       ["secretsmanager:GetSecretValue"], vpc="attached to private app subnets A + B (to reach RDS)")),
    svc("node-iam", "iam", "IAM roles (Lambda + ECS)", SEC, 680, 1180,
        notes="exam-notifier-role: ses:SendEmail (invoked by S3, no queue polling). "
              "exam-marker-role: same SQS actions on marking-queue. Both trust lambda.amazonaws.com.",
        cfg={"executionRole": {"name": "exam-notifier-role", "trust": "lambda.amazonaws.com",
                               "policy": "ses:SendEmail",
                               "actions": ["ses:SendEmail"]},
             "roles": [
                 {"name": "exam-notifier-role", "trust": "lambda.amazonaws.com", "attachedTo": "node-lambda-notify",
                  "actions": ["ses:SendEmail", "ses:SendRawEmail"]},
                 {"name": "exam-marker-role", "trust": "lambda.amazonaws.com", "attachedTo": "node-lambda-mark",
                  "actions": SQS_CONSUME + ["secretsmanager:GetSecretValue"]},
                 {"name": "exam-ecs-task-role", "trust": "ecs-tasks.amazonaws.com", "attachedTo": "node-ecs-a",
                  "actions": ["s3:PutObject", "s3:GetObject", "sqs:SendMessage", "secretsmanager:GetSecretValue"]}]}),
    # security, monitoring, backup, CI/CD (right column)
    svc("node-secrets", "secrets_manager", "Secrets Manager (DB password)", SEC, 1320, 60),
    svc("node-kms", "kms", "KMS (encryption keys)", SEC, 1320, 240),
    svc("node-cloudwatch", "cloudwatch", "CloudWatch (logs + alarms)", MGT, 1320, 420,
        cfg={"alarms": ["5xx errors", "slow responses", "queue backlog", "RDS CPU"]}),
    svc("node-backup", "backup", "AWS Backup (keep 5 years)", STO, 1320, 600),
    svc("node-cicd", "github_actions", "GitHub Actions (CI/CD)", "Developer Tools", 1320, 780,
        cfg={"onPushToMain": ["test", "build + push image to ECR", "terraform apply", "deploy ECS", "upload frontend to S3"]}),
    svc("node-ecr", "ecr_registry", "Amazon ECR (API image)", "Containers", 1320, 960),
]

# ---------- connections: ONE forward line per box on each path ----------
edges = [
    # Walkthrough 1 - open exam + autosave
    edge("node-student", "node-route53", "1. Student opens exams.uni.edu; PUT /api/attempts/{id}/answers every 30 s"),
    edge("node-route53", "node-cloudfront", "2. DNS points to CloudFront"),
    edge("node-cloudfront", "node-alb-a", "3. WAF checks request; /api/* goes to the load balancer"),
    edge("node-alb-a", "node-ecs-a", "4. Load balancer sends it to a healthy API task", proto="HTTP", port=8080),
    edge("node-ecs-a", "node-rds-a", "5. API saves the answers in the database", proto="SQL", port=5432),
    # AZ-B backup path (used when AZ-a is failed)
    edge("node-cloudfront", "node-alb-b", "AZ-a down: traffic goes to the load balancer in AZ-b"),
    edge("node-alb-b", "node-ecs-b", "API task in AZ-b", proto="HTTP", port=8080),
    edge("node-ecs-b", "node-rds-b", "Standby has become the primary after failover", proto="SQL", port=5432),
    # Walkthrough 2 - 40 MB upload + tutor notified
    edge("node-student-upload", "node-s3-files", "1. Browser uploads the 40 MB file straight to S3 (presigned URL)"),
    edge("node-s3-files", "node-lambda-notify", "2. S3 'file uploaded' event invokes the notifier Lambda (asynchronous)"),
    dep("node-lambda-notify", "node-ses", "3. Lambda calls SES SendEmail (email delivery is not simulated by the Lab)"),
    dep("node-ses", "node-tutor", "4. Tutor receives 'new submission' email"),
    # side connections (shown, not simulated)
    dep("node-student", "node-cognito", "Sign in, get a token with role = student"),
    dep("node-student-upload", "node-cloudfront", "Before uploading: API gives a presigned URL (checks PDF/ZIP, <= 50 MB, deadline)"),
    dep("node-cloudfront", "node-waf", "WAF attached to CloudFront"),
    dep("node-cloudfront", "node-s3-web", "Serves the React website"),
    dep("node-rds-a", "node-rds-b", "Multi-AZ: every write copied to the standby", proto="SQL", port=5432),
    dep("node-ecs-a", "node-sqs-mark", "Exam submitted: add marking job"),
    dep("node-sqs-mark", "node-lambda-mark", "Queue triggers the auto-marker"),
    dep("node-lambda-mark", "node-rds-a", "Save MCQ scores", proto="SQL", port=5432),
    dep("node-ecs-b", "node-lambda-notify", "Results released: invoke notifier asynchronously"),
    dep("node-ecs-a", "node-nat-a", "Outbound internet for private tasks"),
    dep("node-ecs-b", "node-nat-b", "Outbound internet for private tasks"),
    dep("node-nat-a", "node-igw", "NAT uses the internet gateway"),
    dep("node-nat-b", "node-igw", "NAT uses the internet gateway"),
    dep("node-ecs-a", "node-secrets", "Read DB password"),
    dep("node-rds-a", "node-kms", "Encrypt data at rest"),
    dep("node-s3-files", "node-kms", "Encrypt files at rest"),
    dep("node-ecs-a", "node-cloudwatch", "Logs and metrics"),
    dep("node-rds-a", "node-backup", "Daily backup kept 5 years"),
    dep("node-lambda-notify", "node-iam", "Uses exam-notifier-role (SES send)"),
    dep("node-lambda-mark", "node-iam", "Uses exam-marker-role (SQS receive/delete)"),
    dep("node-ecs-a", "node-iam", "Uses exam-ecs-task-role"),
    dep("node-cicd", "node-ecr", "Push new API image"),
    dep("node-ecr", "node-ecs-b", "ECS pulls the image"),
]

draft = {
    "format": "aws-architecture-lab", "version": 2,
    "applicationRelease": {"version": "1.0.0", "buildId": "e0a42ea0-ddb8-4c6f-ba18-8fe0f6b62f19",
                           "channel": "stable", "builtAt": "2026-11-08T10:26:50.924Z", "draftVersion": 2},
    "savedAt": "2026-11-18T14:30:00.000Z",
    "state": {
        "draftName": "assignment2", "nodes": nodes, "edges": edges,
        "scenario": {"id": "w1-exam-autosave", "name": "W1 - Student opens exam and answers autosave",
                     "method": "PUT", "path": "/api/attempts/{id}/answers", "startNodeId": "node-student",
                     "trafficLevel": "peak"},
        "simulationResult": None, "activeFailures": [], "activeLabReference": None, "activeChallengeId": None,
        "challengeResult": None, "appMode": "design", "selectedNodeId": None, "selectedEdgeId": None,
        "activeStepIndex": None, "playbackSpeed": 1, "highlightTaskFlow": True, "showNaclSideColumn": False,
        "viewport": {"x": 560, "y": 90, "zoom": 0.4},
    },
}
json.dump(draft, open("assignment2.json", "w"), indent=2)
print("assignment2.json:", sum(n["type"] == "serviceNode" for n in nodes), "services,", len(edges), "connections")
