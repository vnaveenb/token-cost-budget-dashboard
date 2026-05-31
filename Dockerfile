FROM python:3.12.13-slim

RUN groupadd -r dashboard && useradd -r -g dashboard -m dashboard

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data && chown -R dashboard:dashboard /app

USER dashboard

EXPOSE 8100

CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8100"]
