FROM python:3.11-slim

WORKDIR /app

COPY . /app

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

CMD ["python", "/app/app.py"]
