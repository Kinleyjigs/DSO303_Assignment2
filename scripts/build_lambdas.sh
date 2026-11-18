#!/usr/bin/env bash
# Packages the auto-marker Lambda with its PostgreSQL driver and the RDS CA bundle.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf build && mkdir -p build/marker
cp lambdas/marker/marker.py build/marker/
pip install --quiet --no-compile -r lambdas/marker/requirements.txt -t build/marker
curl -fsSL -o build/marker/rds-ca.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
echo "Built build/marker"
