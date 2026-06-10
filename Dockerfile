FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if needed (none for now)

# Copy dependency definition and install
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code
COPY app/ ./app/

# Expose the application port
EXPOSE 8000

# Run FastAPI with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
