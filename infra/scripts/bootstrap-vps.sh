#!/usr/bin/env bash
set -euo pipefail

trap 'echo "[smartdispatch] bootstrap failed on line $LINENO" >&2' ERR

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run this script as root on the VPS." >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
K3S_CHANNEL="${K3S_CHANNEL:-stable}"
STRIMZI_VERSION="${STRIMZI_VERSION:-0.44.0}"

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates \
  curl \
  git \
  gnupg \
  jq \
  lsb-release \
  software-properties-common \
  ufw

ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 6443/tcp
ufw --force enable

if ! command -v k3s >/dev/null 2>&1; then
  curl -sfL https://get.k3s.io | \
    INSTALL_K3S_CHANNEL="${K3S_CHANNEL}" \
    INSTALL_K3S_EXEC="server --disable traefik --disable servicelb --write-kubeconfig-mode 644" \
    sh -
fi

export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"

until kubectl get nodes >/dev/null 2>&1; do
  sleep 5
done

if ! command -v helm >/dev/null 2>&1; then
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx >/dev/null 2>&1 || true
helm repo update
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.hostNetwork=true \
  --set controller.dnsPolicy=ClusterFirstWithHostNet \
  --set controller.service.type=ClusterIP \
  --set controller.admissionWebhooks.enabled=false \
  --wait \
  --timeout 10m

kubectl create namespace kafka --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "https://github.com/strimzi/strimzi-kafka-operator/releases/download/${STRIMZI_VERSION}/strimzi-cluster-operator-${STRIMZI_VERSION}.yaml" -n kafka
kubectl rollout status deployment/strimzi-cluster-operator -n kafka --timeout=10m

echo "SmartDispatch VPS bootstrap complete."
echo "Kubernetes context: ${KUBECONFIG}"
echo "Repo root: ${ROOT_DIR}"