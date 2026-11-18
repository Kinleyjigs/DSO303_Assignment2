#!/usr/bin/env bash
# Usage: ./scripts/create_user.sh <email> <password> <student|tutor|admin>
# Password: 12+ characters with upper case, lower case and a number.
set -euo pipefail
EMAIL=$1; PASSWORD=$2; ROLE=$3
POOL=$(terraform -chdir=infra output -raw cognito_user_pool_id)
aws cognito-idp admin-create-user --user-pool-id "$POOL" --username "$EMAIL" \
  --user-attributes Name=email,Value="$EMAIL" Name=email_verified,Value=true --message-action SUPPRESS >/dev/null
aws cognito-idp admin-set-user-password --user-pool-id "$POOL" --username "$EMAIL" --password "$PASSWORD" --permanent
aws cognito-idp admin-add-user-to-group --user-pool-id "$POOL" --username "$EMAIL" --group-name "$ROLE"
echo "Created $EMAIL as $ROLE"
