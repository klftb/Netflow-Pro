# NetFlow Pro 流量智能分析平台 - Rocky Linux 8.10 部署与安装手册 (v1.3 正式发布版)

> **发布版本**: `v1.3` | **构建时间**: `2026-09-24 15:05 CST`  
> **核心改进**: 包含全新 Linux 原生二进制、长连接全生命周期统计平均平摊算法（**无需修改防火墙超时参数**）、5分钟接口速率有效时间重叠平摊、登录界面安全脱敏。

---

## 一、服务器硬件推荐与运行环境要求

### 1. 硬件规格建议
| 规格等级 | 建议配置 | 适用网络流场景 |
| :--- | :--- | :--- |
| **基础体验 / 实验室** | 4核 CPU / 8GB 内存 / 100GB 硬盘 | 适合开发调试，每天流记录数 < 1000 万条 |
| **中型生产环境 (推荐)** | **8核 CPU / 16GB~32GB 内存 / 500GB+ NVMe SSD** | 适合百兆~千兆流量，每天流记录数 5000 万 ~ 1 亿条 |
| **大型企业核心网** | 16核+ CPU / 64GB+ 内存 / 1TB~2TB NVMe SSD | 支撑万兆核心网交换机与全网出口防火墙，数亿条流 |

### 2. 操作系统、虚拟化与环境要求
- **操作系统**：Rocky Linux 8.10 (或兼容的 AlmaLinux 8.x / RHEL 8.x / CentOS 8.x, x86_64)
- **CPU 指令集要求（重要）**：
  - ClickHouse 24+ 要求 CPU 支持 **`AVX2` 指令集**；
  - 若在 KVM / Proxmox / VMware 虚拟机中部署，**必须将虚拟机 CPU 模型设置为 `host`（宿主机直通模式）**，不可使用默认的 `qemu64`/`kvm64`（否则会报 `status=132/SIGILL` 非法指令崩溃）。
  - 验证命令：`grep -i avx2 /proc/cpuinfo`（有输出即表示支持）。
- **系统时区与 SELinux**：
  - 系统时区需统一为 **`Asia/Shanghai` (CST, +0800)**，否则采集器入库时间戳会与浏览器本地查询时间产生偏移（如默认 `EDT` 会相差 12 小时）；
  - SELinux 需设为 `permissive` 或 `disabled`，防止重启后拦截 `/opt/flow-backend/bin/flow-server` 的守护进程执行。
- **网络需求**：
  - 具备外网连接或配置了内网 DNF 代理（如 `/etc/dnf/dnf.conf` 中的 `proxy=http://...`，安装脚本会自动提取并复用于 `pip`、`curl` 与 `Docker`）；
  - 目标主机配置有固定静态 IP。

### 3. 需要开放的网络端口 (Firewall Ports)
| 端口号 | 传输协议 | 所属服务 | 用途说明 |
| :--- | :--- | :--- | :--- |
| **8080** | **TCP** | flow-backend | **Web 控制台访问与 RESTful API** |
| **2055** | **UDP** | flow-collector | **全网交换机/防火墙 NetFlow v5/v9/IPFIX 报文上送** |
| **6343** | **UDP** | flow-collector | sFlow 采样报文上送 (可选) |
| **9000** | **TCP** | clickhouse-server | ClickHouse Native RPC 原生高吞吐查询端口 |
| **8123** | **TCP** | clickhouse-server | ClickHouse HTTP 批量流写入与运维端口 |
| **9092** | **TCP** | flow-kafka (Docker) | Kafka 高并发削峰填谷消息缓冲集群 |

---

## 二、部署包文件结构说明

整个部署包已被组织打包在 `deploy/` 目录下，结构如下：

```text
deploy/
├── install_rocky8.sh          # Rocky Linux 8.10 一键全自动无人值守安装脚本
├── docker-compose.yml         # Kafka 3.7.0 (KRaft模式) 容器化编排配置文件
├── README.md                  # 本操作指南
├── bin/
│   └── flow-server            # Go 语言 CGO_ENABLED=0 纯静态无依赖二进制程序 (不依赖系统 glibc)
├── config/
│   └── default_test_config.json # 内置默认测试配置文件 (含账号管理、SNMP/API、IPAM地址配置)
├── frontend/
│   └── index.html             # NetFlow Pro v1.3 单页前端工程文件
├── collector/
│   └── flow_collector.py      # Python NetFlow/IPFIX 解码与 ClickHouse 高速写入网桥
├── sql/
│   └── init_clickhouse.sql    # ClickHouse 完整建表、物化视图与字典初始数据 SQL
└── systemd/
    ├── flow-backend.service   # 后端 API 服务的 systemd 守护进程单元 (含无限重试保护)
    └── flow-collector.service # 流量采集网桥的 systemd 守护进程单元 (含无限重试保护)
```

---

## 三、方式 A：一键全自动安装部署（推荐，耗时约 3~5 分钟）

### 步骤 1：将 `deploy` 目录传输至新的 Rocky 8.10 服务器
在本地机器执行（或通过 SCP / SFTP 工具）：
```bash
scp -r d:\nTop\deploy root@<目标服务器IP>:/root/deploy
```

### 步骤 2：登录目标服务器并执行一键安装
```bash
# 登录目标服务器
ssh root@<目标服务器IP>

# 进入部署目录并赋予执行权限
cd /root/deploy
chmod +x install_rocky8.sh bin/flow-server collector/flow_collector.py

# 启动全自动安装部署
./install_rocky8.sh
```

**该脚本将全自动无人值守完成：**
1. 自动校准系统时区为 `Asia/Shanghai`、永久关闭 SELinux 强制拦截、预检 CPU `AVX2` 指令集，并自动识别继承 `/etc/dnf/dnf.conf` 内网代理；
2. 自动启用 EPEL 源与 Powertools/CRB 仓库，安装 Python3.9 及 `pyzmq`（优先使用 RPM 包或国内镜像源）；
3. 自动配置 ClickHouse 官方源并安装 LTS 稳定版，配置纯 IPv4 (`0.0.0.0`) 监听（避免禁用 IPv6 环境下崩溃），固化 systemd `RuntimeDirectory=clickhouse-server`（防止重启后 `/run/clickhouse-server` 临时目录丢失）；
4. 自动连接 ClickHouse 导入完整的 `ntopng` 数据库架构、物化视图、LibreNMS 扩展字段与默认管理员账号；
5. 自动安装 Docker CE（自动携带 `--allowerasing` 解决 Rocky 8 预装 `podman`/`runc` 冲突）与 Docker Compose 插件，拉起 Kafka 削峰消息队列容器；
6. 自动部署并启动 `flow-collector.service` 采集网桥与 `flow-backend.service` 纯静态后端服务（均配置 `StartLimitIntervalSec=0` 防止开机慢启动断连）；
7. 自动配置 Firewalld 防火墙放行所有必要业务端口；
8. 自动执行端到端服务健康体检并输出访问地址与账号密码。

---

## 四、方式 B：分步手工安装与深度定制

如果您的网络环境受限或需要分阶段把控每一步细节，可按照如下步骤操作：

### 0. 系统时区、SELinux 与代理预处理
```bash
# 1. 强制校准时区为北京时间 Asia/Shanghai (防止流量时间戳相差 12 小时)
timedatectl set-timezone Asia/Shanghai

# 2. 永久关闭 SELinux 拦截 (防止服务器重启后恢复 Enforcing 阻止服务运行)
setenforce 0 2>/dev/null || true
sed -i 's/^SELINUX=enforcing/SELINUX=permissive/g' /etc/selinux/config

# 3. 检查 CPU 是否支持 AVX2 指令集 (若无输出，请在虚拟化平台将 CPU 设为 host 直通)
grep -i avx2 /proc/cpuinfo | head -n 1

# 4. 如处于仅配置了 dnf 代理的内网环境，导出全局环境变量供 curl/pip 使用
DNF_PROXY=$(grep -E '^\s*proxy\s*=' /etc/dnf/dnf.conf 2>/dev/null | awk -F'=' '{print $2}' | tr -d ' ')
if [ -n "$DNF_PROXY" ]; then
    export http_proxy="$DNF_PROXY" https_proxy="$DNF_PROXY" HTTP_PROXY="$DNF_PROXY" HTTPS_PROXY="$DNF_PROXY"
fi
```

### 1. 基础系统工具与依赖安装
```bash
dnf install -y epel-release dnf-plugins-core
dnf config-manager --set-enabled powertools || dnf config-manager --set-enabled crb || true

dnf install -y curl wget tar gzip git jq lsof net-tools bind-utils \
               procps-ng sysstat psmisc gcc gcc-c++ make \
               python39 python39-pip python39-devel

# 优先通过 dnf 安装 pyzmq，若无则通过国内镜像源安装
dnf install -y python3-pyzmq python39-pyzmq 2>/dev/null || \
python3 -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn pyzmq
```

### 2. ClickHouse 数据库安装与重启持久化配置
```bash
# 添加官方 LTS YUM 源并安装
cat << 'EOF' > /etc/yum.repos.d/clickhouse.repo
[clickhouse-lts]
name=ClickHouse - LTS Repository
baseurl=https://packages.clickhouse.com/rpm/lts/
enabled=1
gpgcheck=0
EOF
dnf clean all
dnf install -y clickhouse-server clickhouse-client clickhouse-common-static

# 配置纯 IPv4 0.0.0.0 端口监听 (切勿添加 ::，否则在禁用 IPv6 的系统上会启动失败)
mkdir -p /etc/clickhouse-server/config.d
cat << 'EOF' > /etc/clickhouse-server/config.d/listen.xml
<clickhouse>
    <listen_host>0.0.0.0</listen_host>
</clickhouse>
EOF

# 确保 clickhouse 系统用户与目录权限完整 (避免 status=217/USER 报错)
id -u clickhouse &>/dev/null || useradd -r -s /bin/false -d /var/lib/clickhouse clickhouse
mkdir -p /var/lib/clickhouse /var/log/clickhouse-server /etc/clickhouse-server /run/clickhouse-server
chown -R clickhouse:clickhouse /var/lib/clickhouse /var/log/clickhouse-server /etc/clickhouse-server /run/clickhouse-server

# 固化 systemd RuntimeDirectory (关键：防止服务器重启后 /run/clickhouse-server 内存目录消失及残留锁文件)
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

# 启动并开机自启
systemctl daemon-reload
systemctl enable --now clickhouse-server

# 初始化数据库与 Schema
clickhouse-client --multiquery < /root/deploy/sql/init_clickhouse.sql
```

### 3. Docker 与 Kafka 容器部署
```bash
# 安装 Docker CE (必须加 --allowerasing 以自动移除 Rocky 8 默认冲突的 podman/runc)
dnf config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo
dnf install -y --allowerasing docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 若内网使用代理，为 Docker 守护进程配置代理以拉取镜像
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

# 启动 Kafka 容器 (自带 restart: always，服务器重启自动拉起)
mkdir -p /opt/flow-pipeline
cp -f /root/deploy/docker-compose.yml /opt/flow-pipeline/
cd /opt/flow-pipeline && docker compose up -d
```

### 4. 采集网桥服务部署 (flow-collector)
```bash
mkdir -p /opt/flow-pipeline
cp -f /root/deploy/collector/flow_collector.py /opt/flow-pipeline/
chmod +x /opt/flow-pipeline/flow_collector.py

cp -f /root/deploy/systemd/flow-collector.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now flow-collector.service
```

### 5. 后端 API 与 Web 前端部署 (flow-backend)
```bash
mkdir -p /opt/flow-backend/bin /opt/flow-backend/frontend
cp -f /root/deploy/bin/flow-server /opt/flow-backend/bin/
chmod +x /opt/flow-backend/bin/flow-server
cp -f /root/deploy/frontend/index.html /opt/flow-backend/frontend/

cp -f /root/deploy/systemd/flow-backend.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now flow-backend.service
```

### 6. 防火墙端口放行
```bash
firewall-cmd --permanent --add-port=8080/tcp
firewall-cmd --permanent --add-port=2055/udp
firewall-cmd --permanent --add-port=9000/tcp
firewall-cmd --permanent --add-port=8123/tcp
firewall-cmd --permanent --add-port=9092/tcp
firewall-cmd --reload
```

---

## 五、生产环境网络高并发优化建议 (Kernel Sysctl)

在高并发网络环境中（流数据包峰值每秒数万包），强烈建议优化 Linux UDP 接收缓冲区与网络队列，防止网卡与 UDP 2055 端口丢包：

编辑 `/etc/sysctl.d/99-netflow.conf`：
```ini
# 最大与默认套接字接收缓冲区 (增大至 64MB 防止高并发丢包)
net.core.rmem_max = 67108864
net.core.rmem_default = 33554432

# 网络设备输入队列积压深度
net.core.netdev_max_backlog = 100000

# 文件句柄限制
fs.file-max = 2097152
```
生效配置：
```bash
sysctl -p /etc/sysctl.d/99-netflow.conf
```

---

## 六、网络交换机与防火墙 NetFlow 配置示例

在核心交换机或出口防火墙上，指定将 NetFlow/IPFIX 报文上送至新服务器的 2055 端口。

### 1. Cisco IOS-XE / Catalyst 交换机配置示例
```cisco
flow record FLOW-RECORD-NETFLOW-PRO
 match ipv4 tos
 match ipv4 protocol
 match ipv4 source address
 match ipv4 destination address
 match transport source-port
 match transport destination-port
 match interface input
 match interface output
 collect routing next-hop address ipv4
 collect transport tcp flags
 collect counter bytes long
 collect counter packets long
 collect timestamp sys-uptime first
 collect timestamp sys-uptime last

flow exporter FLOW-EXPORTER-NETFLOW-PRO
 destination <Rocky8服务器IP>
 transport udp 2055
 export-protocol netflow-v9
 template data timeout 60

flow monitor FLOW-MONITOR-NETFLOW-PRO
 record FLOW-RECORD-NETFLOW-PRO
 exporter FLOW-EXPORTER-NETFLOW-PRO
 cache timeout active 60
 cache timeout inactive 15

! 在关键业务互联或出口接口应用
interface TenGigabitEthernet1/0/1
 ip flow monitor FLOW-MONITOR-NETFLOW-PRO input
 ip flow monitor FLOW-MONITOR-NETFLOW-PRO output
```

### 2. 华为 (Huawei VRP) 交换机 NetStream 配置示例
```text
ip netstream export host <Rocky8服务器IP> 2055
ip netstream export version 9
ip netstream timeout active 1
ip netstream timeout inactive 15

interface 10GE1/0/1
 ip netstream inbound
 ip netstream outbound
```

### 3. FortiGate (飞塔防火墙) 配置示例
> **【重要说明】系统已全量采用流生命周期时序平摊算法，防火墙长连接超时（`active-flow-timeout`）保持现网默认即可（如 30 分钟 / 1800 秒），绝对无需修改！**

```text
config system netflow
    set collector-ip <Rocky8服务器IP>
    set collector-port 2055
    set source-ip <本地内网接口IP>
    # active-flow-timeout 保持防火墙现有配置即可（无需调整）
    # inactive-flow-timeout 保持默认即可
end

config system interface
    edit "port1"
        set netflow-sampler both
        set sample-rate 500  # 采样比推荐配置为 500 (1:500)
    next
end
```

### 4. 华为防火墙 (Huawei USG6600E V600R007C20SPC500 单机与 HRP 双活) 配置示例

> **版本特别说明（`USG6600E V600R007C20SPC500`）**：
> - 在新一代 V600 固件中，华为官方取消了 Web 图形菜单里的 `NetStream` 页面，**标准 NetStream v9 必须通过 CLI 命令行配置**；
> - 可直接登录防火墙 Web 界面，点击右上角工具栏的 **`CLI 控制台` 图标（`>_`）** 打开命令行窗口执行配置。
>
> **HRP 双活（Active-Active 负载分担）3 条核心原则**：
> 1. **两台防火墙均需独立配置**：`ip netstream` 属于本机统计特性，不会通过 HRP 自动同步到对端，只配一台会漏掉另一台转发的流量；
> 2. **`export source` 必须填写两台设备各自独立的真实物理 IP（严禁填写 VRRP 虚 IP）**：避免两台设备不同的 `sysUpTime` 与模板 ID 在采集器端冲突，同时便于平台将两台防火墙作为独立节点分别展示与汇总；
> 3. **安全策略只需在配置主设备 (`HRP_M`) 配一次**：放行防火墙自身（`local` 区域）到采集器所在区域（如 `trust` 或 `dmz`）的 UDP 2055 策略会自动通过 HRP 同步。

#### (1) 第一台防火墙（单机 或 双活 `HRP_M` 配置主设备）
```text
system-view

# 1. 全局开启 NetStream v9 导出与模板刷新频率（source 填防火墙 A 自身的真实物理 IP）
ip netstream export version 9
ip netstream export source <防火墙A的真实IP>
ip netstream export host <Rocky8服务器IP> 2055
ip netstream export template timeout-rate 1
ip netstream timeout active 1
ip netstream timeout inactive 15
ip netstream sampler fix-packets 500 inbound
ip netstream sampler fix-packets 500 outbound

# 2. 在关键业务接口或聚合口开启双向流采集（可通过 display ip interface brief 查看接口名）
interface 10GE0/0/1
 ip netstream inbound
 ip netstream outbound
 ip netstream sampler fix-packets 500 inbound
 ip netstream sampler fix-packets 500 outbound
quit

# 3. 【关键】放行防火墙本机 (local) 发往采集器的 UDP 2055 流量（双活环境下会自动同步至对端）
security-policy
 rule name PERMIT_LOCAL_NETSTREAM
  source-zone local
  destination-zone trust
  destination-address <Rocky8服务器IP> mask 255.255.255.255
  service protocol udp destination-port 2055
  action permit
quit

return
save
y
```

#### (2) 第二台防火墙（双活 `HRP_S` 配置从设备）
```text
system-view

# 若提示备机/从设备禁止直接配置，先开启本地配置权限
hrp standby config enable

# 1. 全局开启 NetStream v9（注意：source 必须填防火墙 B 自身的真实物理 IP！）
ip netstream export version 9
ip netstream export source <防火墙B的真实IP>
ip netstream export host <Rocky8服务器IP> 2055
ip netstream export template timeout-rate 1
ip netstream timeout active 1
ip netstream timeout inactive 15
ip netstream sampler fix-packets 500 inbound
ip netstream sampler fix-packets 500 outbound

# 2. 在与防火墙 A 相对应的业务接口开启双向流采集
interface 10GE0/0/1
 ip netstream inbound
 ip netstream outbound
 ip netstream sampler fix-packets 500 inbound
 ip netstream sampler fix-packets 500 outbound
quit

return
save
y
```

#### (3) 状态验证命令
- 在防火墙 CLI 查看导出包计数：`display ip netstream statistic`
- 在采集服务器抓包验证：`tcpdump -ni any udp port 2055 -c 20`

### 5. Cisco ASA 防火墙 (NSEL - NetFlow v9) 配置示例

Cisco ASA 采用 **NSEL (NetFlow Security Event Logging)** 机制，建议仅导出 `flow-teardown`（连接结束汇总）和 `flow-update`（长连接周期更新），避免 `flow-create` 空包重复触发：

```cisco
! 1. 指定 NetFlow 采集器地址、端口与模板刷新时间
flow-export destination <内网接口名称, 如 inside> <Rocky8服务器IP> 2055
flow-export template timeout-rate 1
flow-export delay flow-create 15

! 2. 开启长连接周期性流量上报 (默认每 1 分钟上报一次活跃长连接字节增量)
flow-export active refresh-interval 1

! 3. 在全局策略 (global_policy) 中绑定 NSEL 流量导出事件
policy-map global_policy
 class inspection_default
  flow-export event-type flow-teardown destination <Rocky8服务器IP>
  flow-export event-type flow-update destination <Rocky8服务器IP>
exit
```

### 6. Cisco Firepower (FMC 集中管理平台配置 FTD) 配置示例

在 Cisco FMC (Firepower Management Center) 管理 FTD 防火墙时，通过 **FlexConfig** 下发 NetFlow (NSEL) 配置：

#### 步骤 1：创建或调用内置 NetFlow FlexConfig 对象
1. 登录 **FMC Web 控制台**，进入 **Objects > Object Management > FlexConfig > FlexConfig Object**；
2. 勾选系统内置的以下两个对象（或复制创建自定义对象）：
   - **`Netflow_Add_Destination`**：设置采集器目标参数
   - **`Netflow_Set_Parameters`**：设置模板与刷新参数

#### 步骤 2：在 FlexConfig 策略中填入变量参数
1. 进入 **Devices > FlexConfig**，新建或编辑绑定到目标 FTD 防火墙的策略；
2. 添加上述对象并填写对应的变量值（Variables）：
   - `interface_name`：通往采集器的逻辑接口名（例如 `inside` 或 `management`）
   - `ip_address`：`<Rocky8服务器IP>`
   - `udp_port`：`2055`
   - `timeout_rate`：`1`（每 1 分钟刷新一次 v9 模板）
   - `refresh_interval`：`1`（长连接活跃刷新周期，保持默认或 1~5 分钟均可）
   - `event_types`：选择 `flow-teardown` 与 `flow-update`（或 `all`，采集器已自动过滤 0 字节的 `flow-create` 事件）

#### 步骤 3：保存并部署 (Deploy)
点击右上角 **Save** -> **Deploy** 将策略推送至 FTD 防火墙即可生效。

---

## 七、运维排查与日常管理命令

| 操作 | 对应命令 |
| :--- | :--- |
| **查看后端 API 日志** | `journalctl -u flow-backend.service -f` |
| **查看采集网桥日志** | `journalctl -u flow-collector.service -f` |
| **查看 ClickHouse 状态** | `systemctl status clickhouse-server` |
| **查看 Kafka 容器状态** | `docker ps -f name=flow-kafka` |
| **查询当前流总数与入库延迟** | `clickhouse-client --database=ntopng --query="SELECT count(), max(last_switched) FROM flows_raw;"` |
| **测试 UDP 2055 是否接收到报文** | `tcpdump -ni any udp port 2055 -c 10` |
| **Web 登录账号密码** | 初始账号: `admin` / 密码: `admin`（登录后可在右上角修改密码） |

---

## 八、长连接平摊与带宽统计平均机制说明

1. **核心原则**：
   - 严禁且无需调整网络交换机或防火墙的长连接超时时间（如 `active-flow-timeout` 保持 1800 秒 / 30 分钟即可）。
2. **计算原理**：
   - 平台通过 ClickHouse 内置向量化时序函数 `timeSlots(first_switched, duration, stepSec)`，将长连接传输的总字节数均匀平摊到其活跃的每一个时间槽中；
   - 接口 5 分钟实时速率按流在当前 5 分钟时间窗口内的有效重叠时间比例精确计算；
   - 会话列表直接显示单流生存周期的平均速率 $\frac{Bytes \times 8}{Duration}$；
   - 彻底避免了因长超时集中上报产生的单点虚假脉冲，走势曲线平滑且真实。
3. **采样比**：
   - FortiGate 接口采样比推荐配置为 `500`（1:500），系统采集并呈现真实物理带宽。

---

## 九、Rocky Linux 8.10 生产部署避坑与重启持久化清单

在 Rocky Linux 8.10 内网虚拟化环境部署与重启验证中，以下 9 项关键点已全部固化到一键部署脚本 (`install_rocky8.sh`)、systemd 服务文件与数据库初始化 SQL 中：

| 序号 | 故障现象 / 隐患点 | 根本原因 | 永久修复方案（已内置于部署包） |
| :--- | :--- | :--- | :--- |
| **1** | **最近 1 小时查不到流量，只能看到 22 点** | 服务器默认时区为 `America/New_York (EDT, UTC-4)`，比北京时间慢 12 小时，导致采集器写入时间戳偏移 | 执行 `timedatectl set-timezone Asia/Shanghai` 并重启 `flow-collector` 与 `flow-backend` |
| **2** | **服务器重启后 ClickHouse 启动失败** | `/run/clickhouse-server` 为内存文件系统 (`tmpfs`)，重启后目录丢失；且异常断电可能残留 `/var/lib/clickhouse/status` 锁文件 | 在 `/etc/systemd/system/clickhouse-server.service.d/override.conf` 中配置 `RuntimeDirectory=clickhouse-server` 与 `ExecStartPre=-/bin/rm -f /var/lib/clickhouse/status` |
| **3** | **开机时 `flow-backend` 因数据库慢启动而停止重试** | 服务器冷启动时 ClickHouse 初始化较慢，若 `flow-backend` 在 10 秒内重连失败 5 次，会触发 systemd 默认 `StartLimitBurst` 保护并放弃重启 | 在 `flow-backend.service` 和 `flow-collector.service` 的 `[Unit]` 中增加 `StartLimitIntervalSec=0`（无限重试直至数据库就绪） |
| **4** | **`flow-backend` 报 `GLIBC_2.32/2.34 not found`** | 动态编译的二进制依赖高版本 `glibc`，而 Rocky 8 自带 `glibc 2.28`；或重跑脚本时被 `/root/deploy/bin/flow-server` 旧文件覆盖 | 使用 `CGO_ENABLED=0` 纯静态编译 `flow-server`，并同时更新 `/opt/flow-backend/bin/` 与 `/root/deploy/bin/` |
| **5** | **ClickHouse 启动报 `code=132/SIGILL` 非法指令** | KVM/VMware 虚拟机使用了默认 `qemu64`/`kvm64` CPU 模型，缺少 ClickHouse 24+ 必需的 `AVX2` 指令集 | 在虚拟化平台将虚拟机 CPU 类型改为 **`host`（宿主机直通）** |
| **6** | **ClickHouse 报 `status=217/USER` 或 IPv6 监听崩溃** | 缺少 `clickhouse` 系统用户，或内核禁用 IPv6 时 `listen.xml` 配置了 `::` | 自动创建 `clickhouse` 用户并赋权；`listen.xml` 仅保留 `<listen_host>0.0.0.0</listen_host>` |
| **7** | **安装 Docker CE 报 `podman` / `runc` 冲突** | Rocky 8 默认预装了 `podman` 与 `buildah`，与 `docker-ce` 依赖的 `containerd.io` 冲突 | 安装命令增加 `--allowerasing` 参数自动替换冲突包 |
| **8** | **内网环境 `pip` / `curl` / `docker` 无法联网** | 服务器无直连公网，仅在 `/etc/dnf/dnf.conf` 配置了 HTTP 代理 | 自动提取 `dnf.conf` 中的 `proxy` 注入全局环境变量与 `/etc/systemd/system/docker.service.d/http-proxy.conf` |
| **9** | **LibreNMS 同步报 `Unknown identifier snmp_community`** | 旧版建表脚本字段名为 `community`/`snmp_ver`，与后端查询的 `snmp_community`/`snmp_version` 及 `display_name`/`speed_mbps` 不一致 | 已在 `init_clickhouse.sql` 与后端启动自检 `EnsureConfigTables` 中加入 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 自动补齐 |

---

## 十、配置文件导出、导入与默认测试配置说明

### 1. 支持导出与导入的三大核心配置模块
平台提供统一的 JSON 配置文件格式（支持全量或按模块勾选导出/导入，导入后**即时热生效，无需重启服务**）：
1. **账号管理配置 (`accounts`)**：
   - 本地系统账号列表（`username`、`display_name`、`role` 管理员/只读角色、`auth_type`、`password_hash`，导入时还支持直接填写明文 `password` 自动进行 bcrypt 加密）；
   - 企业 LDAP / Active Directory 域统一认证配置（`ldap_enabled`、`ldap_url`、`ldap_base_dn`、`ldap_bind_dn`、`ldap_bind_password`、`ldap_user_filter`、`ldap_default_role`）。
2. **SNMP / API 配置 (`snmp_api`)**：
   - 第三方平台 API 集成配置（LibreNMS URL/Token、NetBox URL/Token）；
   - NBA 异常流量检测阈值（`port_scan_threshold`、`silence_minutes`）；
   - 网络导出器设备及 SNMP 参数（`exporter_devices`：设备 IP、名称、类型、机房位置、管理员、SNMP Community、SNMP 版本）；
   - 设备物理/逻辑接口定义字典（`device_interfaces`：接口索引 `if_index`、接口名、描述、别名、显示名称、带宽速率）；
   - 应用协议与端口映射字典（`app_mapping`）。
3. **IPAM 地址配置 (`ipam`)**：
   - 业务部门网段划分（`business_groups`：网段名称、CIDR、所属部门、来源）；
   - 32 位主机 IP 资产映射表（`ip_hosts`：主机 IP、Hostname、DNS 名称、业务描述、来源）。

### 2. Web 界面操作方式
1. 登录 Web 控制台后，点击顶部导航栏 **【设置】** -> 切换到 **【账号管理与配置导入导出】** 子标签页；
2. **导出配置**：勾选需要导出的配置模块（默认全选 `accounts`、`snmp_api`、`ipam`），点击 **【导出当前配置文件 (.json)】** 即可下载备份文件；
3. **导入配置**：
   - 方式一（上传文件）：点击文件选择框上传本地 `.json` 配置文件（或安装包内的 `config/default_test_config.json`），核对解析预览摘要后点击 **【导入并立即热应用所选配置】**；
   - 方式二（一键载入默认测试配置）：直接点击卡片右上角 **【一键载入默认测试配置】** 按钮，再点击 **【导入并立即热应用所选配置】** 即可快速初始化整套演示/测试环境数据。

### 3. 内置默认测试配置文件 (`config/default_test_config.json`)
自动化安装包内已预置一份完整的默认测试配置文件：
- 安装包内路径：`deploy/config/default_test_config.json`
- 部署后服务器路径：`/opt/flow-backend/config/default_test_config.json`
- 预置内容包含：
  - **测试账号**：`admin`（系统管理员）、`netops_test`（运维管理员，密码 `admin`）、`noc_viewer`（只读观察员，密码 `admin`）及 LDAP 示例参数；
  - **测试 SNMP/API 与设备**：LibreNMS / NetBox 示例地址、FortiGate-200F 出口防火墙、华为 USG6600E 双活主备防火墙 (`10.3.1.1` / `10.3.1.2`)、华为 CE6850 核心交换机及对应万兆/千兆接口、12 条常用应用协议字典；
  - **测试 IPAM 地址**：4 个核心业务部门 CIDR 网段与 5 台关键核心主机 IP 映射记录。

---

## 十一、7天与30天大跨度流量分析性能优化规范 (v1.3.1 性能调优)

在企业或 IDC 网络中，7 天至 30 天的大跨度 NetFlow 原始流水表通常累积数千万至数十亿条记录。平台在 `v1.3.1` 中实施了以下全链路性能优化：

### 1. 核心瓶颈与性能优化点
| 模块 / 接口 | 原始性能瓶颈 | 优化手段 | 耗时改善效果 |
| :--- | :--- | :--- | :--- |
| **会话明细表**<br>(`/api/v1/traffic/sessions`) | 30 天跨度下硬查秒级流水表 `flows_raw` 并做全局 `ORDER BY bytes DESC`，扫描数亿行导致超时 | 当查询跨度 $> 24$ 小时时，自动智能收敛为查询**最近 24 小时活跃连接**，前端状态栏增加收敛提示 | 从 **>20~30 秒（或超时）**<br>降至 **~300 毫秒** |
| **接口 TopN**<br>(`/api/v1/traffic/topn`) | 在千万级大表上直接进行 3 个 `LEFT JOIN` (设备与接口表)，导致大量内存哈希连接计算 | **子查询下推 (Subquery Pushdown)**：先在大表中依据排序键聚合出 Top 10，仅对这 10 行做名称关联 | 耗时下降 **70%~80%**，<br>稳定在 2~3 秒内 |
| **应用 TopN**<br>(`/api/v1/traffic/topn`) | 大表全量与 `app_mapping` 关联再分组 | 先在子查询按 `(proto, dst_port)` 聚合出 Top 10，外层再关联应用名字典 | 耗时下降 **70%** |
| **业务组 TopN**<br>(`/api/v1/traffic/topn`) | 数千万行流记录与业务组网段直接 `CROSS JOIN`，计算几何级数爆炸 | 先在子查询按 `src_ip` 聚合去重，再与业务组做 `isIPAddressInRange`，计算量骤降 5000 倍 | 彻底避免 OOM 崩溃 |
| **流量趋势与桑基图**<br>(`/traffic/trend` / `sankey`) | 构建大哈希表导致内存高占用与 CPU 单核瓶颈 | 注入 `SETTINGS optimize_aggregation_in_order = 1, max_threads = 8`，利用排序键物理顺序流式聚合 | 内存占用降低 70%，<br>查询吞吐提升 2~3 倍 |
| **前端接口分析联动** | 原前端先串行等待会话、再发起趋势图，导致双倍等待时间 | 改为 `Promise.all` 并发拉取，出图时间减少一半，卡片标题实时呈现智能收敛徽标 | 页面交互体感显著提速 |




