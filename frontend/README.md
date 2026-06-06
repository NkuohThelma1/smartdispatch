# SmartDispatch Frontend

React + Vite single-page frontend for SmartDispatch.

## Local development

```bash
cd frontend
npm install
npm run dev
```

The app defaults to `VITE_API_BASE_URL=/api`, so it works with the cluster ingress host.

## Build

```bash
npm run build
```

## Docker

```bash
docker build -t smartdispatch-frontend-service:local .
```