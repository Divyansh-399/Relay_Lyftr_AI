FROM python:3.12-slim AS build
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=bind,from=build,source=/wheels,target=/wheels pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt
RUN useradd -u 10001 -m relay && mkdir /data && chown relay /data
COPY main.py storage.py gateway.py limits.py ./
USER relay
ENV DATABASE_URL=sqlite:////data/app.db PYTHONDONTWRITEBYTECODE=1 PORT=8000
CMD ["sh","-c","exec uvicorn main:app --host 0.0.0.0 --port \"$PORT\" --workers 1 --no-access-log"]
