FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ /app/app/

# Create directory for SQLite database
RUN mkdir -p /data

# Default port, can be overridden with APP_PORT environment variable
ENV APP_PORT=8000
EXPOSE $APP_PORT

# Start FastAPI application
CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT}"
