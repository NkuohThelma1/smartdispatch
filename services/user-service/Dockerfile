# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Don't write .pyc files to disk, don't buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# Copy only requirements first — Docker caches this layer separately.
# If requirements.txt hasn't changed, Docker skips pip install on rebuild.
COPY requirements.txt .

# Install dependencies into an isolated folder /install
# --no-cache-dir keeps the image smaller (no pip cache stored)
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: final image ──────────────────────────────────────────────────────
FROM python:3.12-slim AS final

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create a non-root user with UID 10001 (lecturer requires UID ≥ 10001)
# -r = system account, -u = set UID, no home directory needed
RUN adduser --system --uid 10001 --no-create-home appuser

WORKDIR /app

# Copy installed packages from builder stage into the final image
COPY --from=builder /install /usr/local

# Copy only the app source code — nothing else goes into the image
COPY app/ ./app/
COPY requirements.txt .

# Give appuser ownership of the working directory
RUN chown -R appuser /app

# Switch to non-root user — all commands after this run as appuser
USER appuser

# Tell Docker this container listens on port 8001
EXPOSE 8001

# Start the FastAPI app using uvicorn
# app.main:app means: inside the app/ folder, main.py file, the `app` FastAPI instance
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]