# Playwright's official image includes Chromium + Linux dependencies.
# This alpha visits ONLY the bundled localhost practice website.
FROM mcr.microsoft.com/playwright/python:v1.57.0-noble
WORKDIR /app
RUN python -m pip install --no-cache-dir 'playwright==1.57.0' \
 && useradd -m -u 65532 -s /usr/sbin/nologin demo
COPY app.py browser_lab.py household.py ./
COPY static ./static
RUN mkdir -p /app/data && chown 65532:65532 /app/data
USER 65532:65532
ENV OMNIXAT_DEMO_DB=/app/data/demo.sqlite3 \
    PYTHONDONTWRITEBYTECODE=1
EXPOSE 8765
CMD ["python", "app.py", "--host", "0.0.0.0"]
