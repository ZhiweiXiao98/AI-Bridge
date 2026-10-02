#!/bin/bash
# PySide6 沙盒环境构建和测试脚本

set -e  # 遇到错误立即退出

echo "======================================================================"
echo "🐳 PySide6 沙盒环境构建和测试"
echo "======================================================================"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 步骤 1: 构建 Docker 镜像
echo ""
echo "${YELLOW}[步骤 1/3] 构建 Docker 镜像...${NC}"
echo "----------------------------------------------------------------------"

cd app/core/sandbox

if docker build -t ai-bridge-sandbox:pyside6 -f Dockerfile ../../..; then
    echo "${GREEN}✅ Docker 镜像构建成功${NC}"
else
    echo "${RED}❌ Docker 镜像构建失败${NC}"
    exit 1
fi

cd ../../..

# 步骤 2: 运行 PySide6 测试
echo ""
echo "${YELLOW}[步骤 2/3] 运行 PySide6 测试...${NC}"
echo "----------------------------------------------------------------------"

if docker run --rm \
    -v "$(pwd):/workspace" \
    -e QT_QPA_PLATFORM=offscreen \
    ai-bridge-sandbox:pyside6 \
    python test_pyside6.py; then
    echo "${GREEN}✅ PySide6 测试通过${NC}"
else
    echo "${RED}❌ PySide6 测试失败${NC}"
    exit 1
fi

# 步骤 3: 运行插件系统测试
echo ""
echo "${YELLOW}[步骤 3/3] 运行插件系统测试...${NC}"
echo "----------------------------------------------------------------------"

if docker run --rm \
    -v "$(pwd):/workspace" \
    -e QT_QPA_PLATFORM=offscreen \
    ai-bridge-sandbox:pyside6 \
    python test_plugin_system.py; then
    echo "${GREEN}✅ 插件系统测试通过${NC}"
else
    echo "${RED}❌ 插件系统测试失败${NC}"
    exit 1
fi

echo ""
echo "======================================================================"
echo "${GREEN}✅ 所有测试通过！${NC}"
echo "======================================================================"
echo ""
echo "📦 Docker 镜像: ai-bridge-sandbox:pyside6"
echo "🎨 PySide6 版本: 6.6.0+"
echo "✅ GUI 测试环境已就绪"
echo ""
echo "使用方法："
echo "  # 进入容器交互式 shell"
echo "  docker run -it --rm -v \$(pwd):/workspace ai-bridge-sandbox:pyside6 bash"
echo ""
echo "  # 运行 Python 脚本"
echo "  docker run --rm -v \$(pwd):/workspace ai-bridge-sandbox:pyside6 python your_script.py"
echo ""
