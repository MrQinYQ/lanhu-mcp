FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 设置构建时代理参数
ARG HTTP_PROXY
ARG HTTPS_PROXY

# 设置环境变量
ENV HTTP_PROXY=${HTTP_PROXY}
ENV HTTPS_PROXY=${HTTPS_PROXY}
ENV PYTHONUNBUFFERED=1

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    gnupg \
    ca-certificates \
    nodejs \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 安装Playwright浏览器
RUN playwright install chromium
RUN playwright install-deps chromium

# 复制MCP服务器文件
COPY lanhu_mcp_server.py .
COPY lanhu_codegen ./lanhu_codegen

# 创建数据和日志目录
RUN mkdir -p /app/data /app/logs

# 清理代理环境变量
ENV HTTP_PROXY=
ENV HTTPS_PROXY=

# 暴露端口
EXPOSE 8000

# 运行MCP服务器（使用HTTP传输）
CMD ["python", "lanhu_mcp_server.py"]
