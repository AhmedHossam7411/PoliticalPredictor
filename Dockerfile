# FastAPI backend image — runs on Hugging Face Spaces, Koyeb, Fly.io, Cloud Run, etc.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only the backend needs to ship (the frontend is hosted on Vercel).
COPY predictor ./predictor
COPY baseline_speeches ./baseline_speeches

# Most hosts inject $PORT (Koyeb, Cloud Run). Hugging Face Spaces uses 7860.
ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn predictor.api:app --host 0.0.0.0 --port ${PORT}"]
