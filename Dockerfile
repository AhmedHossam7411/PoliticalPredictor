# FastAPI backend image. Used by the self-hosted kit in deploy/ (and any Docker host).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Backend only; the frontend has its own image (frontend/Dockerfile).
COPY predictor ./predictor
COPY baseline_speeches ./baseline_speeches
# Arabic mock speeches = the Arabic norming corpus for the dictionary scorer.
COPY sample_speeches_ar ./sample_speeches_ar
# VICS word lists (only QI/QP get past .dockerignore).
COPY ["VICS Code/VICS Code", "./VICS Code/VICS Code"]

# Most hosts inject $PORT (Koyeb, Cloud Run). Hugging Face Spaces uses 7860.
ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn predictor.api:app --host 0.0.0.0 --port ${PORT}"]
