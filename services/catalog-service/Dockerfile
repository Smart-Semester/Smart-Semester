FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY catalog_app ./catalog_app

EXPOSE 8001

CMD ["uvicorn", "catalog_app.main:app", "--host", "0.0.0.0", "--port", "8001"]
