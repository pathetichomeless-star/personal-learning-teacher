FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libopus0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
    "aiohttp>=3.9,<4" "opuslib"

COPY app /app/app
COPY config /app/config
COPY tests /app/tests

USER 10001
ENV PYTHONUNBUFFERED=1

EXPOSE 8110 8111

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8111/health', timeout=4).status==200 else 1)"

CMD ["python", "-m", "app.main"]