FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency definition
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir -e .

# Copy application code
COPY . .

# Expose ports: 8000 for FastAPI API, 8501 for Streamlit UI
EXPOSE 8000 8501

# Default command launches FastAPI gateway; can be overridden to streamlit run app.py
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
