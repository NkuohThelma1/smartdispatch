# SmartDispatch E2E Tests

End-to-end smoke tests for the SmartDispatch frontend, exercising signup, login, order placement, order tracking, and analytics against a live docker-compose stack.

## Prerequisites

- Node.js 20+
- npm
- Docker and Docker Compose
- Playwright browsers (installed via `npx playwright install`)

## Setup

1. Install frontend dependencies (including Playwright):
   ```bash
   cd frontend
   npm install
   ```

2. Install Playwright browsers and OS dependencies:
   ```bash
   cd tests/e2e
   npx playwright install --with-deps
   ```

## Running the Stack

Start the full docker-compose stack (Kafka, services, frontend):
```bash
docker compose up --build
```

Wait until all services are healthy. The frontend will be available at `http://localhost:8080`.

## Running the Tests

From the `tests/e2e` directory:
```bash
npx playwright test
```

Run with UI for debugging:
```bash
npx playwright test --ui
```

Run a single test file:
```bash
npx playwright test full-flow.spec.ts
```

## Viewing Results

### HTML Report
After a test run, open the HTML report:
```bash
npx playwright show-report
```

### Trace on Failure
If a test fails, Playwright captures a trace (when `trace: 'on-first-retry'` is set). To view it:
```bash
npx playwright show-trace trace.zip
```

Or open the HTML report and click the failed test to inspect the trace, screenshots, and video.

## Notes

- These tests require a **live stack** and are **not** part of the automated CI unit-test suite.
- Run them manually as a pre-demo smoke test.
- Each test run generates a unique phone number based on a timestamp to avoid signup conflicts.
- The analytics assertions include a retry window (up to 30s) to account for Kafka event propagation latency.
- Tests target the frontend served by docker-compose on port `8080`, which proxies `/api` to the backend microservices via nginx.

## Troubleshooting

- **Frontend nginx changes have no effect**: `nginx.conf` is baked into the frontend image at build time. After editing it, always run `docker compose build frontend` before `docker compose up -d`.
- **Backend services crash on startup**: The 5 backend services depend on Kafka being healthy first. Before running tests, run `docker compose ps -a` and confirm every backend service shows `Up` (not `Exited`). If any exited, Kafka wasn't ready yet — restart with `docker compose up -d`.
- **Signup fails with "phone already registered"**: The test uses a timestamp-based phone number. If you see this error, wait a moment and retry.
- **Analytics never update**: Ensure the `analytics-service` is healthy and consuming Kafka events. Check `docker compose logs analytics-service`.
