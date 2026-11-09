FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    --default-timeout=120 \
    -r requirements.txt

# 含 app/assets/captcha/*.jpg|png|webp，验证码背景唯一来源；勿在 .dockerignore 排除
COPY app ./app

RUN mkdir -p /app/data \
    && test -d /app/app/assets/captcha \
    && test "$(find /app/app/assets/captcha -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \) | wc -l)" -gt 0

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
