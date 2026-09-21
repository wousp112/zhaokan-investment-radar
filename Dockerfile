FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RADAR_DATA_DIR=/app/data
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home radar
COPY app ./app
RUN mkdir -p /app/data && chown -R radar:radar /app
USER radar
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=4)"
CMD ["python","-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","1"]
