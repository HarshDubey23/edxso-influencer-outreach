#!/usr/bin/env bash
# Deploy to one always-on Google Compute Engine VM (e2-micro, inside the free tier) with HTTPS.
#   bash deploy/gcp.sh            first deploy or update (re-run after every git push)
# Needs: gcloud signed in (gcloud auth login), a project with billing enabled, and a filled-in .env next to this repo.
# Why a VM and not Cloud Run: the autopilot is a background loop and SQLite needs a persistent disk.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
ZONE="${ZONE:-us-central1-a}"
VM="${VM:-outreach-engine}"
[ -n "$PROJECT" ] || { echo "Set a project: gcloud config set project <id>"; exit 1; }
[ -f .env ] || { echo "Missing .env"; exit 1; }
g() { gcloud --quiet --project "$PROJECT" "$@"; }

g services enable compute.googleapis.com >/dev/null
if ! g compute instances describe "$VM" --zone "$ZONE" >/dev/null 2>&1; then
  echo "Creating VM $VM in $ZONE"
  g compute instances create "$VM" --zone "$ZONE" --machine-type e2-micro \
    --image-family debian-12 --image-project debian-cloud --boot-disk-size 30GB --boot-disk-type pd-standard \
    --tags outreach-web \
    --metadata startup-script='#!/bin/bash
command -v docker >/dev/null || (curl -fsSL https://get.docker.com | sh)
fallocate -l 1G /swapfile 2>/dev/null && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile || true'
  g compute firewall-rules describe outreach-web >/dev/null 2>&1 || \
    g compute firewall-rules create outreach-web --allow tcp:80,tcp:443 --target-tags outreach-web
fi

IP=$(g compute instances describe "$VM" --zone "$ZONE" --format 'value(networkInterfaces[0].accessConfigs[0].natIP)')
DOMAIN="${DOMAIN:-${IP//./-}.sslip.io}"
echo "Public URL: https://$DOMAIN"

echo "Waiting for Docker on the VM"
until g compute ssh "$VM" --zone "$ZONE" --command 'command -v docker' >/dev/null 2>&1; do sleep 10; done

# Ship the code (tracked files only) and the .env; secrets travel over SSH, never through a web form.
git archive --format=tar.gz -o /tmp/outreach.tgz HEAD
g compute scp /tmp/outreach.tgz .env "$VM":~ --zone "$ZONE"
g compute ssh "$VM" --zone "$ZONE" --command "set -e
mkdir -p app && tar -xzf outreach.tgz -C app && mv .env app/.env && cd app
sed -i '/^BASE_URL=/d;/^WORKSPACE_ONLY=/d' .env
echo 'DOMAIN=$DOMAIN' > deploy/.env
cd deploy && sudo docker compose up -d --build && sudo docker compose ps"

echo
echo "Done: https://$DOMAIN"
echo "Add this redirect URI to your Google OAuth client: https://$DOMAIN/auth/google/callback"
