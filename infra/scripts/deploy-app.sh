#!/usr/bin/env bash
set -euo pipefail

trap 'echo "[smartdispatch] deploy failed on line $LINENO" >&2' ERR

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

if ! command -v ansible-playbook >/dev/null 2>&1; then
  echo "ansible-playbook is required for this deploy step." >&2
  exit 1
fi

ansible-playbook \
  -i "${ROOT_DIR}/ansible/inventory/hosts.ini" \
  "${ROOT_DIR}/ansible/playbooks/site.yml" \
  --extra-vars "image_tag=${IMAGE_TAG}" \
  --extra-vars "namespace=smartdispatch" \
  --extra-vars "release_name=smartdispatch"