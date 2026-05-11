# filename: app/core/sandbox/Dockerfile
# AI Bridge 沙盒环境 (V2 Clean Edition)

FROM python:3.14-slim

ENV TZ=Asia/Shanghai
ENV LANG=C.UTF-8
WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/workspace
ENV PIP_NO_CACHE_DIR=1

# [系统依赖] 精简版，移除 GUI 相关
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN pip install --upgrade pip

# [RAG 引擎] 保留供沙盒内代码使用
RUN pip install \
    "chromadb>=0.4.24" \
    "fastembed>=0.2.0" \
    "onnxruntime>=1.18.0" \
    "pydantic>=2.0"

# [工具链]
RUN pip install \
    numpy \
    pandas \
    requests \
    beautifulsoup4 \
    python-dotenv \
    pytest \
    pytest-asyncio \
    httpx \
    networkx \
    tiktoken

# 容器保活
CMD ["tail", "-f", "/dev/null"]