"""
Assignment 2 - Task 1 diagrams (diagrams-as-code).
pip install diagrams  (needs Graphviz)  ->  python diagram.py
Outputs: architecture.png, walkthrough-1-exam-autosave.png, walkthrough-2-upload-notify.png
"""
from diagrams import Diagram, Cluster, Edge
from diagrams.aws.general import Users
from diagrams.aws.network import Route53, CloudFront, ALB, NATGateway, InternetGateway
from diagrams.aws.security import WAF, Cognito, SecretsManager, KMS
from diagrams.aws.compute import Fargate, Lambda, ECR
from diagrams.aws.database import RDS
from diagrams.aws.storage import S3, Backup
from diagrams.aws.integration import SQS
from diagrams.aws.engagement import SES
from diagrams.aws.management import Cloudwatch
from diagrams.onprem.ci import GithubActions

BLUE = dict(color="#1f6feb", penwidth="2.2", fontcolor="#1f6feb", fontsize="13")
ORANGE = dict(color="#d9480f", penwidth="2.2", fontcolor="#d9480f", fontsize="13")
GREY = dict(color="#868e96", style="dashed")
G = {"fontsize": "22", "pad": "0.5", "nodesep": "0.5", "ranksep": "1.0", "splines": "spline"}

# ------------------------------------------------------------ full architecture
with Diagram("Online Exam Platform - Architecture (1 Region, 2 Availability Zones)",
             filename="architecture", show=False, direction="LR", graph_attr=G):
    student = Users("Students /\nTutors / Admins")

    with Cluster("1. Edge"):
        dns = Route53("Route 53\n(DNS)")
        cdn = CloudFront("CloudFront\n(CDN + HTTPS)")
        waf = WAF("WAF\n(firewall)")
    with Cluster("2. Frontend + Sign-in"):
        web = S3("S3 website\n(React app)")
        auth = Cognito("Cognito\nstudent/tutor/admin")

    with Cluster("VPC 10.0.0.0/16"):
        igw = InternetGateway("Internet\ngateway")
        with Cluster("Availability Zone A"):
            with Cluster("Public subnet"):
                alb_a = ALB("Load balancer")
                nat_a = NATGateway("NAT A")
            with Cluster("Private app subnet"):
                api_a = Fargate("API\n(ECS Fargate)")
            with Cluster("Private DB subnet"):
                db_a = RDS("RDS PRIMARY")
        with Cluster("Availability Zone B"):
            with Cluster("Public subnet "):
                alb_b = ALB("Load balancer")
                nat_b = NATGateway("NAT B")
            with Cluster("Private app subnet "):
                api_b = Fargate("API\n(ECS Fargate)")
            with Cluster("Private DB subnet "):
                db_b = RDS("RDS STANDBY")

    with Cluster("3. File storage"):
        files = S3("S3 submissions\nencrypted, lifecycle:\nIA 90d > Glacier 1y\n> delete 5y")
    with Cluster("4. Async processing"):
        l_notify = Lambda("notifier\n(invoked by S3)")
        ses = SES("SES (email)")
        q_mark = SQS("marking-queue")
        l_mark = Lambda("MCQ auto-marker")
    with Cluster("5. Security, monitoring, backup"):
        secrets = SecretsManager("Secrets Manager")
        kms = KMS("KMS keys")
        cw = Cloudwatch("CloudWatch")
        backup = Backup("AWS Backup\n(5 years)")
    with Cluster("6. CI/CD"):
        gha = GithubActions("GitHub Actions\n(push to main)")
        ecr = ECR("ECR\n(API image)")

    student >> dns >> cdn
    waf - Edge(style="dashed") - cdn
    cdn >> web
    student >> Edge(style="dashed") >> auth
    cdn >> Edge(label="/api/*") >> igw
    igw >> alb_a >> api_a >> db_a
    igw >> alb_b >> api_b >> db_b
    db_a - Edge(label="Multi-AZ\nsync copy", color="black", penwidth="2") - db_b
    student >> Edge(label="upload with\npresigned URL", color="#d9480f") >> files
    files >> Edge(label="upload event") >> l_notify >> ses
    api_a >> Edge(**GREY) >> q_mark >> l_mark >> Edge(**GREY) >> db_a
    api_b >> Edge(label="results released", **GREY) >> l_notify
    api_a >> Edge(**GREY) >> nat_a
    api_b >> Edge(**GREY) >> nat_b
    api_b >> Edge(**GREY) >> secrets
    db_b >> Edge(**GREY) >> kms
    api_b >> Edge(**GREY) >> cw
    db_b >> Edge(**GREY) >> backup
    gha >> ecr >> Edge(**GREY) >> api_a

# ------------------------------------------------------------ walkthrough 1
with Diagram("Walkthrough 1 - Student opens an exam and answers autosave",
             filename="walkthrough-1-exam-autosave", show=False, direction="LR",
             graph_attr={"fontsize": "20", "pad": "0.4", "ranksep": "1.1"}):
    s = Users("Student")
    auth = Cognito("Cognito")
    r53 = Route53("Route 53")
    cf = CloudFront("CloudFront + WAF")
    with Cluster("VPC (load balancer in public subnets, API + DB in private subnets)"):
        lb = ALB("Load balancer")
        api = Fargate("API (ECS)")
        pri = RDS("RDS primary (AZ-a)")
        sby = RDS("RDS standby (AZ-b)")
    s >> Edge(label="1 sign in", **BLUE) >> auth
    s >> Edge(label="2 open exam", **BLUE) >> r53 >> Edge(**BLUE) >> cf
    cf >> Edge(label="3 /api/*", **BLUE) >> lb >> Edge(label="4", **BLUE) >> api
    api >> Edge(label="5 save answers\nevery 30 s", **BLUE) >> pri
    pri >> Edge(label="6 instant copy", **BLUE) >> sby

# ------------------------------------------------------------ walkthrough 2
with Diagram("Walkthrough 2 - Student uploads a 40 MB assignment and the tutor is notified",
             filename="walkthrough-2-upload-notify", show=False, direction="LR",
             graph_attr={"fontsize": "20", "pad": "0.4", "ranksep": "1.1"}):
    s = Users("Student")
    api = Fargate("API (ECS)")
    bucket = S3("S3 submissions")
    fn = Lambda("notifier")
    mail = SES("SES")
    t = Users("Tutor")
    s >> Edge(label="1 ask to upload (PDF/ZIP, 40 MB)\n2 API checks it, returns presigned URL", dir="both", **ORANGE) >> api
    s >> Edge(label="3 upload file\ndirectly to S3", **ORANGE) >> bucket
    bucket >> Edge(label="4 'file uploaded' event\ninvokes Lambda", **ORANGE) >> fn
    fn >> Edge(label="5 send email", **ORANGE) >> mail
    mail >> Edge(label="6 'new submission'", **ORANGE) >> t
