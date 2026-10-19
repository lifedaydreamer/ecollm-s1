FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY requirements.lock ./
COPY tradepilot tradepilot
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps .
COPY data data
COPY migrations migrations
COPY alembic.ini ./
RUN useradd -m app && mkdir -p /app/.data && chown -R app:app /app
USER app
ENV TRADEPILOT_DATA=/app/.data
CMD ["uvicorn","tradepilot.api:app_factory","--factory","--host","0.0.0.0","--port","8100","--workers","1"]
