#!/bin/bash
# ==============================================================================
# NetFlow Pro 流量智能分析平台 - Rocky Linux 8.10 一键全自动安装部署脚本
# 适用系统: Rocky Linux 8.x / AlmaLinux 8.x / RHEL 8.x / CentOS 8.x (x86_64)
# ==============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${CYAN}==================================================================${NC}"
echo -e "${CYAN}   NetFlow Pro 流量智能分析平台 - Rocky Linux 8.10 一键部署向导   ${NC}"
echo -e "${CYAN}   版本: v1.3 发布版 | 构建日期: 2026-09-24 | 支持长连接平摊算法  ${NC}"
echo -e "${CYAN}==================================================================${NC}"

# 1. 检查是否为 root 用户
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}[ERROR] 本脚本必须以 root 权限运行，请使用 'sudo bash $0' 执行。${NC}"
   exit 1
fi

# 2. 检查操作系统版本、时区、SELinux 与 CPU AVX2 指令集
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_NAME=$NAME
    OS_VER=$VERSION_ID
    echo -e "${GREEN}[*] 检测到操作系统: ${OS_NAME} ${OS_VER}${NC}"
else
    echo -e "${YELLOW}[!] 无法读取 /etc/os-release，请确保为 RHEL/Rocky 8.x 系统。${NC}"
fi

# 统一系统时区为 Asia/Shanghai (防止采集入库时间戳与浏览器北京时间偏移)
echo -e "${GREEN}[*] 正在校准系统时区为 Asia/Shanghai (CST, +0800)...${NC}"
timedatectl set-timezone Asia/Shanghai 2>/dev/null || ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime

# 关闭 SELinux 强制拦截 (防止重启后恢复 Enforcing 阻止 systemd 自定义服务执行)
setenforce 0 2>/dev/null || true
if [ -f /etc/selinux/config ]; then
    sed -i 's/^SELINUX=enforcing/SELINUX=permissive/g' /etc/selinux/config 2>/dev/null || true
fi

# 预检 CPU AVX2 指令集 (ClickHouse 24+ 要求虚拟化 CPU 开启 host 直通支持 AVX2)
if ! grep -qi "avx2" /proc/cpuinfo; then
    echo -e "${RED}[ERROR] 当前 CPU 未检测到 AVX2 指令集支持！ClickHouse 启动将会触发 SIGILL (code=132) 崩溃。${NC}"
    echo -e "${YELLOW}[!] 请在虚拟化平台 (KVM/Proxmox/VMware) 中将该虚拟机 CPU 类型切换为 'host' (宿主机直通) 后再运行。${NC}"
    exit 1
fi

# 自动检测并继承 dnf/yum 代理 (针对无直连互联网、仅配置 dnf 代理的环境)
DNF_PROXY=$(grep -E '^\s*proxy\s*=' /etc/dnf/dnf.conf /etc/yum.conf 2>/dev/null | head -n 1 | awk -F'=' '{print $2}' | tr -d ' ')
if [ -n "$DNF_PROXY" ]; then
    echo -e "${GREEN}[*] 检测到系统 dnf 代理: ${DNF_PROXY}${NC}"
    echo -e "${GREEN}[*] 正在将代理同步映射至 http_proxy / https_proxy，供 pip/curl 等工具复用...${NC}"
    export http_proxy="$DNF_PROXY"
    export https_proxy="$DNF_PROXY"
    export HTTP_PROXY="$DNF_PROXY"
    export HTTPS_PROXY="$DNF_PROXY"
fi

# 3. 基础依赖与 EPEL 源配置
echo -e "\n${BLUE}[Step 1/8] 配置基础环境与安装常用系统依赖包...${NC}"
dnf install -y epel-release dnf-plugins-core
dnf config-manager --set-enabled powertools || dnf config-manager --set-enabled crb || true

dnf install -y \
    curl wget tar gzip git jq lsof net-tools bind-utils \
    procps-ng sysstat psmisc gcc gcc-c++ make \
    python39 python39-pip python39-devel

# 安装 pyzmq (优先尝试 EPEL 原生 rpm，其次使用国内清华/阿里高速镜像源，避免境外 PyPI 超时)
if ! python3 -c "import zmq" &>/dev/null; then
    dnf install -y python3-pyzmq python39-pyzmq 2>/dev/null || true
fi

if ! python3 -c "import zmq" &>/dev/null; then
    echo -e "${YELLOW}[*] 通过国内高速镜像源安装 Python pyzmq 依赖库...${NC}"
    python3 -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn --timeout 15 pyzmq || \
    python3 -m pip install -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com --timeout 15 pyzmq || \
    python3 -m pip install pyzmq || true
fi

if python3 -c "import zmq" &>/dev/null; then
    echo -e "${GREEN}[+] Python pyzmq 消息队列组件安装成功${NC}"
else
    echo -e "${YELLOW}[!] 警告: pyzmq 暂未就绪，将在 flow-collector 启动前再次检测${NC}"
fi

# 4. 安装 ClickHouse 列式高性能时序数据库
echo -e "\n${BLUE}[Step 2/8] 安装与配置 ClickHouse 数据库 (24.x LTS)...${NC}"
if ! command -v clickhouse-server &> /dev/null; then
    cat << 'EOF' > /etc/yum.repos.d/clickhouse.repo
[clickhouse-lts]
name=ClickHouse - LTS Repository
baseurl=https://packages.clickhouse.com/rpm/lts/
enabled=1
gpgcheck=0
EOF
    dnf clean all
    dnf install -y clickhouse-server clickhouse-client clickhouse-common-static
fi

# 开启全网段本地 0.0.0.0 监听 (纯 IPv4，避免 IPv6 禁用环境下的冲突)
mkdir -p /etc/clickhouse-server/config.d
cat << 'EOF' > /etc/clickhouse-server/config.d/listen.xml
<clickhouse>
    <listen_host>0.0.0.0</listen_host>
</clickhouse>
EOF

# 固化 systemd RuntimeDirectory 配置 (防止服务器重启后 /run/clickhouse-server 临时目录丢失及残留锁文件)
mkdir -p /etc/systemd/system/clickhouse-server.service.d
cat << 'EOF' > /etc/systemd/system/clickhouse-server.service.d/override.conf
[Unit]
StartLimitIntervalSec=0

[Service]
Type=simple
NotifyAccess=all
RuntimeDirectory=clickhouse-server
RuntimeDirectoryMode=0755
ExecStartPre=-/bin/rm -f /var/lib/clickhouse/status
EOF

# 确保 clickhouse 守护进程用户与目录权限完整 (解决 status=217/USER 错误)
if ! id -u clickhouse &>/dev/null; then
    groupadd -r clickhouse 2>/dev/null || true
    useradd -r -g clickhouse -s /bin/false -d /var/lib/clickhouse clickhouse 2>/dev/null || true
fi
mkdir -p /var/lib/clickhouse /var/log/clickhouse-server /etc/clickhouse-server /run/clickhouse-server
chown -R clickhouse:clickhouse /var/lib/clickhouse /var/log/clickhouse-server /etc/clickhouse-server /run/clickhouse-server

systemctl daemon-reload
systemctl enable clickhouse-server

if ! clickhouse-client --query "SELECT 1" &>/dev/null; then
    rm -f /var/lib/clickhouse/status 2>/dev/null || true
    systemctl restart clickhouse-server
fi

echo -e "${BLUE}[*] 正在等待 ClickHouse 数据库初始化与端口就绪...${NC}"
CH_READY=0
for i in {1..30}; do
    if clickhouse-client --query "SELECT 1" &>/dev/null; then
        CH_READY=1
        break
    fi
    sleep 1
done

if [ $CH_READY -eq 1 ]; then
    echo -e "${GREEN}[+] ClickHouse 数据库服务已成功启动并就绪 (Port: 9000 Native / 8123 HTTP)${NC}"
else
    echo -e "${RED}[ERROR] ClickHouse 服务启动超时异常，请检查 'journalctl -u clickhouse-server'${NC}"
    exit 1
fi

# 5. 初始化数据库表结构与预置数据
echo -e "\n${BLUE}[Step 3/8] 初始化 ClickHouse 数据库 Schema 与默认应用字典...${NC}"
if [ -f "${SCRIPT_DIR}/sql/init_clickhouse.sql" ]; then
    clickhouse-client --multiquery < "${SCRIPT_DIR}/sql/init_clickhouse.sql"
    # 兼容补齐已有环境可能缺失的扩展字段 (LibreNMS SNMP 与接口显示字段)
    clickhouse-client -q "ALTER TABLE ntopng.exporter_devices ADD COLUMN IF NOT EXISTS snmp_community String;" 2>/dev/null || true
    clickhouse-client -q "ALTER TABLE ntopng.exporter_devices ADD COLUMN IF NOT EXISTS snmp_version String DEFAULT '2c';" 2>/dev/null || true
    clickhouse-client -q "ALTER TABLE ntopng.device_interfaces ADD COLUMN IF NOT EXISTS display_name String;" 2>/dev/null || true
    clickhouse-client -q "ALTER TABLE ntopng.device_interfaces ADD COLUMN IF NOT EXISTS speed_mbps UInt32;" 2>/dev/null || true
    echo -e "${GREEN}[+] 成功导入完整表结构与字典配置 (ntopng.flows_raw, flows_5m, exporter_devices, system_users)${NC}"
else
    echo -e "${YELLOW}[!] 未在 ${SCRIPT_DIR}/sql 找到 init_clickhouse.sql，后端服务将自动尝试初始化建表。${NC}"
fi

# 6. 安装 Docker Engine 与启动 Kafka 消息缓冲容器
echo -e "\n${BLUE}[Step 4/8] 安装 Docker 并启动 Kafka 流消息削峰缓冲集群...${NC}"
if ! command -v docker &> /dev/null; then
    dnf config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo 2>/dev/null || \
    dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
    dnf install -y --allowerasing docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

if [ -n "$DNF_PROXY" ]; then
    mkdir -p /etc/systemd/system/docker.service.d
    cat << EOF > /etc/systemd/system/docker.service.d/http-proxy.conf
[Service]
Environment="HTTP_PROXY=${DNF_PROXY}"
Environment="HTTPS_PROXY=${DNF_PROXY}"
Environment="NO_PROXY=localhost,127.0.0.1,::1"
EOF
    systemctl daemon-reload
fi

systemctl enable --now docker
sleep 2

mkdir -p /opt/flow-pipeline
if [ -f "${SCRIPT_DIR}/docker-compose.yml" ]; then
    cp -f "${SCRIPT_DIR}/docker-compose.yml" /opt/flow-pipeline/docker-compose.yml
fi

cd /opt/flow-pipeline
docker compose pull kafka || docker compose pull || true
docker compose up -d
sleep 3

if docker ps | grep -q "flow-kafka"; then
    echo -e "${GREEN}[+] Kafka 缓冲队列容器已启动 (Port: 9092, KRaft 模式)${NC}"
else
    echo -e "${YELLOW}[!] 警告: Kafka 容器未能立即检测到，请稍后检查 'docker ps'${NC}"
fi

# 7. 部署 NetFlow/IPFIX 采集网桥服务 (flow-collector)
echo -e "\n${BLUE}[Step 5/8] 部署 NetFlow/sFlow/IPFIX 采集网桥服务...${NC}"
mkdir -p /opt/flow-pipeline
if [ -f "${SCRIPT_DIR}/collector/flow_collector.py" ]; then
    cp -f "${SCRIPT_DIR}/collector/flow_collector.py" /opt/flow-pipeline/flow_collector.py
    chmod +x /opt/flow-pipeline/flow_collector.py
fi

if [ -f "${SCRIPT_DIR}/systemd/flow-collector.service" ]; then
    cp -f "${SCRIPT_DIR}/systemd/flow-collector.service" /etc/systemd/system/flow-collector.service
fi

systemctl daemon-reload
systemctl enable --now flow-collector.service
sleep 2

if systemctl is-active --quiet flow-collector.service; then
    echo -e "${GREEN}[+] NetFlow 采集网桥服务已成功启动 (Listening UDP 2055)${NC}"
else
    echo -e "${YELLOW}[!] 警告: flow-collector 服务未处于 active 状态，请查看 systemctl status flow-collector${NC}"
fi

# 8. 部署 Akvorado 流分析与后端 API 服务 (flow-backend)
echo -e "\n${BLUE}[Step 6/8] 编译与部署 Akvorado 流分析后端 API 与前端 Web 控制台...${NC}"
mkdir -p /opt/flow-backend/bin /opt/flow-backend/frontend /opt/flow-backend/config

if [ -d "${SCRIPT_DIR}/backend" ] && [ -f "${SCRIPT_DIR}/backend/cmd/server/main.go" ]; then
    echo -e "${BLUE}[*] 检测到后端 Go 源码 (${SCRIPT_DIR}/backend)，正在目标主机直接编译纯静态二进制...${NC}"
    if [ -x "/usr/local/go/bin/go" ]; then
        export PATH="/usr/local/go/bin:$PATH"
    fi
    if ! command -v go &>/dev/null; then
        dnf install -y golang
    fi
    (
        cd "${SCRIPT_DIR}/backend"
        export GOPROXY="https://goproxy.cn,https://goproxy.io,direct"
        export GOSUMDB="sum.golang.google.cn"
        export GOTOOLCHAIN="auto"
        CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o "${SCRIPT_DIR}/bin/flow-server" ./cmd/server
    ) && echo -e "${GREEN}[+] 后端纯静态二进制 flow-server 本地编译成功！${NC}" || echo -e "${YELLOW}[!] 源码编译未完成，将使用安装包预置二进制${NC}"
fi

if [ -f "${SCRIPT_DIR}/bin/flow-server" ]; then
    cp -f "${SCRIPT_DIR}/bin/flow-server" /opt/flow-backend/bin/flow-server
    chmod +x /opt/flow-backend/bin/flow-server
fi

if [ -f "${SCRIPT_DIR}/frontend/index.html" ]; then
    cp -f "${SCRIPT_DIR}/frontend/index.html" /opt/flow-backend/frontend/index.html
fi

if [ -f "${SCRIPT_DIR}/config/default_test_config.json" ]; then
    cp -f "${SCRIPT_DIR}/config/default_test_config.json" /opt/flow-backend/config/default_test_config.json
    echo -e "${GREEN}[+] 已生成默认测试配置文件: /opt/flow-backend/config/default_test_config.json${NC}"
fi

if [ -f "${SCRIPT_DIR}/systemd/flow-backend.service" ]; then
    cp -f "${SCRIPT_DIR}/systemd/flow-backend.service" /etc/systemd/system/flow-backend.service
fi

systemctl daemon-reload
systemctl enable --now flow-backend.service
sleep 2

if systemctl is-active --quiet flow-backend.service; then
    echo -e "${GREEN}[+] flow-backend 核心服务已成功运行 (Listening HTTP 8080)${NC}"
else
    echo -e "${RED}[ERROR] flow-backend 启动异常，请检查 'journalctl -u flow-backend'${NC}"
    exit 1
fi

# 9. 配置防火墙端口 (Firewalld)
echo -e "\n${BLUE}[Step 7/8] 配置防火墙端口策略 (Firewalld)...${NC}"
if systemctl is-active --quiet firewalld; then
    firewall-cmd --permanent --add-port=8080/tcp # Web & API
    firewall-cmd --permanent --add-port=2055/udp # NetFlow / IPFIX
    firewall-cmd --permanent --add-port=6343/udp # sFlow
    firewall-cmd --permanent --add-port=9000/tcp # ClickHouse Native
    firewall-cmd --permanent --add-port=8123/tcp # ClickHouse HTTP
    firewall-cmd --permanent --add-port=9092/tcp # Kafka
    firewall-cmd --reload
    echo -e "${GREEN}[+] 防火墙策略已放行 8080(Web), 2055(NetFlow UDP), 8123(HTTP), 9000(CH), 9092(Kafka)${NC}"
else
    echo -e "${YELLOW}[*] firewalld 未运行，跳过防火墙规则追加${NC}"
fi

# 10. 服务状态巡检与验证
echo -e "\n${BLUE}[Step 8/8] 执行部署后全链条自动化健康检测...${NC}"
LOCAL_IP=$(ip route get 8.8.8.8 2>/dev/null | awk '{print $7}' || hostname -I | awk '{print $1}')

sleep 2
HEALTH_RESP=$(curl -s http://127.0.0.1:8080/api/v1/health || true)

echo -e "\n${GREEN}==================================================================${NC}"
echo -e "${GREEN}      🎉 恭喜！NetFlow Pro 流量智能分析平台已在 Rocky 8.10 安装完成！     ${NC}"
echo -e "${GREEN}==================================================================${NC}"
echo -e "平台访问地址: ${CYAN}http://${LOCAL_IP}:8080${NC}"
echo -e "默认登录账号: ${YELLOW}admin${NC}"
echo -e "默认登录密码: ${YELLOW}admin${NC}"
echo -e "默认测试配置: ${CYAN}/opt/flow-backend/config/default_test_config.json${NC}"
echo -e "  (可在 Web 界面【设置 -> 账号管理与配置导入导出】一键载入或上传导入)"
echo -e "\n核心基础服务状态:"
echo -e "  - flow-backend:      $(systemctl is-active flow-backend.service)"
echo -e "  - clickhouse-server: $(systemctl is-active clickhouse-server.service)"
echo -e "  - flow-collector:    $(systemctl is-active flow-collector.service)"
echo -e "  - flow-kafka:        $(docker inspect -f '{{.State.Status}}' flow-kafka 2>/dev/null || echo 'unknown')"
echo -e "\n交换机 / 防火墙 NetFlow 配置目标:"
echo -e "  - 目标 IP:   ${CYAN}${LOCAL_IP}${NC}"
echo -e "  - 目标端口: ${CYAN}2055 (UDP)${NC}"
echo -e "  - 报文协议: ${CYAN}NetFlow v5 / v9 / IPFIX (v10)${NC}"
echo -e "=================================================================="
