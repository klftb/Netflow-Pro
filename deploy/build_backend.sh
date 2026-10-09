#!/bin/bash
# ==============================================================================
# NetFlow Pro - 目标 Linux 服务器直接编译与热更新脚本 (build_backend.sh)
# 作用: 在目标服务器上直接将 backend 源码编译为纯静态二进制并热更新服务
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_SRC="${SCRIPT_DIR}/backend"

echo "=================================================================="
echo "   NetFlow Pro 后端源码本地直接编译与更新脚本 (Pure Static Build)"
echo "=================================================================="

# 1. 自动继承系统 DNF/YUM 代理 (若内网配置了代理)
DNF_PROXY=$(grep -E '^\s*proxy\s*=' /etc/dnf/dnf.conf /etc/yum.conf 2>/dev/null | head -n 1 | awk -F'=' '{print $2}' | tr -d ' ')
if [ -n "$DNF_PROXY" ]; then
    echo "[*] 检测到系统代理: ${DNF_PROXY}，正在注入编译环境..."
    export http_proxy="$DNF_PROXY"
    export https_proxy="$DNF_PROXY"
    export HTTP_PROXY="$DNF_PROXY"
    export HTTPS_PROXY="$DNF_PROXY"
fi

# 2. 检查并安装 Go 编译器
if [ -x "/usr/local/go/bin/go" ]; then
    export PATH="/usr/local/go/bin:$PATH"
fi

if ! command -v go &>/dev/null; then
    echo "[*] 未检测到 go 命令，正在通过 dnf 安装 golang 编译工具链..."
    dnf install -y golang git
fi

echo "[*] 当前 Go 引导版本: $(go version)"

# 3. 执行纯静态无依赖编译 (CGO_ENABLED=0)
cd "${BACKEND_SRC}"
export GOPROXY="https://goproxy.cn,https://goproxy.io,direct"
export GOSUMDB="sum.golang.google.cn"
export GOTOOLCHAIN="auto"

echo "[*] 正在拉取依赖并编译纯静态二进制 flow-server (CGO_ENABLED=0)..."
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o "${SCRIPT_DIR}/bin/flow-server" ./cmd/server
chmod +x "${SCRIPT_DIR}/bin/flow-server"

echo "[+] 编译成功: $(file "${SCRIPT_DIR}/bin/flow-server")"

# 4. 同步部署到 /opt/flow-backend 并重启服务
mkdir -p /opt/flow-backend/bin /opt/flow-backend/frontend /opt/flow-backend/config
cp -f "${SCRIPT_DIR}/bin/flow-server" /opt/flow-backend/bin/flow-server
chmod +x /opt/flow-backend/bin/flow-server

if [ -f "${SCRIPT_DIR}/frontend/index.html" ]; then
    cp -f "${SCRIPT_DIR}/frontend/index.html" /opt/flow-backend/frontend/index.html
fi

if [ -f "${SCRIPT_DIR}/config/default_test_config.json" ]; then
    cp -f "${SCRIPT_DIR}/config/default_test_config.json" /opt/flow-backend/config/default_test_config.json
fi

if systemctl list-unit-files | grep -q "flow-backend.service"; then
    echo "[*] 正在重启 flow-backend.service..."
    systemctl restart flow-backend.service
    sleep 2
    systemctl status flow-backend.service --no-pager
fi

echo "=================================================================="
echo "[+] 编译与热更新全部完成！"
echo "=================================================================="
