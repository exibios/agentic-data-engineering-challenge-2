FROM python:3.11-slim
WORKDIR /app
ENV PORT=8080 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pipeline/ ./pipeline/
COPY agent/ ./agent/
CMD ["uvicorn", "pipeline.main:app", "--host", "0.0.0.0", "--port", "8080"]
