#!/usr/bin/env bash
# Tears everything down. Buckets, ECR and the backup vault are emptied automatically (force_destroy).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d build/marker ] || ./scripts/build_lambdas.sh
terraform -chdir=infra destroy -auto-approve "$@"
echo "Platform destroyed. To also remove the state bucket and deploy role: cd bootstrap && terraform destroy"
