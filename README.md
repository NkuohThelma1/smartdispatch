# smartdispatch
SmartDispatch: Scalable Multi-Business Delivery Platform — Microservices, K8s, Kafka

## Infrastructure

VPS/bootstrap scripts and the deployment view are documented in [infra/README.md](infra/README.md).

## Observability

The services expose Prometheus metrics on `/metrics`, and the repository includes a small observability stack in `manifests/observability.yaml`.

To install it:

```bash
kubectl apply -f manifests/observability.yaml
kubectl create configmap smartdispatch-dashboard \
	--from-file=smartdispatch.json=dashboards/smartdispatch.json \
	-n observability \
	--dry-run=client -o yaml | kubectl apply -f -
```

Prometheus runs on port `9090` and Grafana runs on port `3000`. Port-forward either service if you want a local UI.

## CI

The Jenkins pipeline now runs Python unit tests before building images, then scans, pushes, and deploys the Helm release.

## Frontend

The repository now includes a React + Vite frontend under `frontend/`.

Run it locally with:

```bash
cd frontend
npm install
npm run dev
```

By default the app talks to the backend through `/api`, so it works with the same host/ingress setup as the cluster.

## Ansible

The Kubernetes bootstrap and deployment flow is available under `ansible/playbooks/`.

Typical usage:

```bash
ansible-playbook -i ansible/inventory/hosts.ini ansible/playbooks/site.yml
```

`bootstrap.yml` applies the namespace, Kafka, observability, and network policy manifests. `deploy.yml` runs the Helm umbrella chart for the application stack.
