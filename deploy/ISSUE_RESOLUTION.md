# NetFlow Pro 核心运维与性能故障排查手册 (Issue Resolution Knowledgebase)

> **文档标识**: `ISSUE-20261009-PERF-DEPLOY`  
> **适用版本**: NetFlow Pro v1.3 / v1.3.1  
> **涉及操作系统**: Rocky Linux 8.x / AlmaLinux 8.x / CentOS 7.x / Ubuntu 22.04+  
> **最后更新时间**: 2026-10-09  

---

## 目录
1. [Issue #001：7天/30天大跨度流量分析查询严重卡顿与超时](#issue-0017天30天大跨度流量分析查询严重卡顿与超时)
2. [Issue #002：SCP 在线覆盖更新运行中程序报 `Text file busy / Failure`](#issue-002scp-在线覆盖更新运行中程序报-text-file-busy--failure)
3. [Issue #003：Rocky Linux 8 跨平台部署报 `status=1/FAILURE` 闪退崩溃](#issue-003rocky-linux-8-跨平台部署报-status1failure-闪退崩溃)
4. [生产环境极速平滑热升级 SOP](#生产环境极速平滑热升级-sop)

---

## Issue #001：7天/30天大跨度流量分析查询严重卡顿与超时

### 1. 问题现象
* **触发场景**：用户在 Web 控制台的【仪表盘 (Dashboard)】或【接口与会话流量分析】页面，将时间范围由默认的 1小时/24小时 切换至 **7天** 或 **30天**（或指定单台核心设备查询 30 天）。
* **故障表现**：整个页面进入长时间转圈卡死状态，前端等待 **15秒 ~ 48秒** 甚至直接触发 Nginx/浏览器超时；服务器 CPU 核心打满，磁盘 I/O 剧烈飙升。

### 2. 深度根因分析 (Root Causes)
通过在 10.3.11.78 真实数据库（单台核心设备流记录超 1.33 亿行）抓取 SQL 执行计划，定位到三大深层瓶颈：

1. **接口会话明细表 (`/traffic/sessions`) 硬查底层原始流表**：
   * 原代码在大时间跨度下仍硬编码查询原始秒级流水表 `ntopng.flows_raw`，并执行 `ORDER BY bytes DESC LIMIT 50`。
   * 30 天内包含数亿条未聚合原始流，ClickHouse 必须对数亿行数据进行全局内存排序，导致单次会话查询耗时超过 20~30 秒。
2. **仪表盘桑基图 (`/traffic/sankey`) 高基数三元组未剪枝哈希聚合（最大元凶）**：
   * 桑基图需要聚合 `(src_ip, dst_ip, dst_port)`。在 30 天跨度下，单台设备（如 `10.3.251.1`）累计了 1.33 亿行数据。
   * 原 SQL 对 1.33 亿行数据中包含的数十万种微碎 IP/端口组合全量构建哈希表，**单查询实测耗时整整 47.96 秒**！
3. **前端 `Promise.all` 导致的短板阻塞效应**：
   * 前端通过 `Promise.all([trendPromise, fetchTopN(), fetchSankey()])` 并发拉取。
   * 尽管核心趋势折线图只需 1.5~2.6 秒即可计算完成，但由于必须等待 48 秒的桑基图返回，全局 loading 遮罩层被强制锁定，导致已经算好的趋势大图迟迟无法展现给用户。

### 3. 完整解决方案与代码实现

#### (1) 后端：会话明细大跨度智能收敛保护
在 `backend/internal/repository/clickhouse.go` 中，当时间跨度 $> 24$ 小时时，自动将明细会话流查询窗口收敛为最近 24 小时活跃连接：
```go
if duration > 24*time.Hour {
    isClipped = true
    notice = "时间跨度超过24小时，会话明细已智能收敛展示最近24小时活跃连接"
    clippedStart := endTime.Add(-24 * time.Hour)
    startStr = clippedStart.Format("2006-01-02 15:04:05")
}
```
* **效果**：物理扫描行数减少 95% 以上，会话接口耗时由 **>30秒 骤降至 315毫秒**。

#### (2) 后端：桑基图两阶段 Top Talker 剪枝优化 (Two-Stage Pruning)
在 30 天跨度下，只有全网总流量最大的活跃源主机才可能进入 Top 15 流向。引入子查询索引剪枝：
```sql
SELECT src_ip, dst_ip, dst_port, sum(bytes) AS vol
FROM ntopng.flows_5m
WHERE time_bucket >= ... AND exporter_ip = ...
  AND src_ip IN (
      SELECT src_ip
      FROM ntopng.flows_5m
      WHERE time_bucket >= ... AND exporter_ip = ...
      GROUP BY src_ip
      ORDER BY sum(bytes) DESC
      LIMIT 25
  )
GROUP BY src_ip, dst_ip, dst_port
ORDER BY vol DESC LIMIT 15
SETTINGS max_threads = 8
```
* **效果**：参与三元哈希聚合的行数直接下降 90% 以上，**单查询耗时从 47.96 秒暴降至 4.14 秒，提速 11 倍**。

#### (3) 后端：TopN 子查询下推与流式聚合
* **接口 TopN**：先在大表按 `(exporter_ip, in_snmp, out_snmp)` 聚合出 Top 10，外层仅对这 10 行与字典表做 `LEFT JOIN`，消除千万级大表全量 JOIN。
* **流式聚合设置**：注入 `SETTINGS optimize_aggregation_in_order = 1, max_threads = 8`，利用物理主键排序流式聚合，内存开销降低约 70%。

#### (4) 前端：瀑布式优先出图 (Waterfall Rendering)
重构 `frontend/index.html` 中的 `fetchData`，优先等待核心趋势图出图：
```javascript
// 优先等待核心趋势折线图（1.5s~2.6s 内返回），出图后立即呈现大屏，解除阻塞
await trendPromise;
loading.value = false;

// TopN 排行榜与桑基图在后台继续并发加载
await Promise.all([fetchTopN(), fetchSankey()]);
```
* **效果**：用户切换 30 天后，**核心折线图与总吞吐率卡片 2 秒内立刻呈现**，彻底消除死等卡顿感。

---

## Issue #002：SCP 在线覆盖更新运行中程序报 `Text file busy / Failure`

### 1. 问题现象
* **触发场景**：从本地电脑通过 `scp` 命令直接尝试覆盖目标 Linux 主机上正在运行的程序：
  ```powershell
  scp d:/nTop/deploy/bin/flow-server root@10.36.6.13:/opt/flow-backend/bin/flow-server
  ```
* **报错信息**：
  ```text
  C:\WINDOWS\System32\OpenSSH\scp.exe: dest open "/opt/flow-backend/bin/flow-server": Failure
  C:\WINDOWS\System32\OpenSSH\scp.exe: failed to upload file
  ```

### 2. 深度根因分析
* **Linux 内核 `ETXTBSY` 保护机制**：
  当一个二进制程序正在被系统守护进程（`flow-backend.service`）执行时，内核会锁定该可执行文件对应的 inode text 镜像。
* `scp` 默认以“只写并清空（`O_WRONLY | O_CREAT | O_TRUNC`）”模式打开目标文件，试图直接覆写正在运行的文件镜像，直接被 Linux 内核返回 `ETXTBSY (Text file busy)` 拒绝。

### 3. 标准解决流程
利用 Linux 的 **`mv` (rename) 原子替换机制**（重命名操作只改变目录项指针，不修改运行中进程持有的原 inode）：

1. **第一步（本地上传）**：统一上传到通用的 `/tmp/` 目录：
   ```powershell
   scp d:/nTop/deploy/bin/flow-server root@<TARGET_IP>:/tmp/flow-server
   ```
2. **第二步（目标机覆盖）**：在目标服务器上执行 `mv` 覆盖：
   ```bash
   mv /tmp/flow-server /opt/flow-backend/bin/flow-server
   chmod +x /opt/flow-backend/bin/flow-server
   systemctl restart flow-backend
   ```

---

## Issue #003：Rocky Linux 8 跨平台部署报 `status=1/FAILURE` 闪退崩溃

### 1. 问题现象
* **触发场景**：将编译好的 `flow-server` 上传至目标主机（`cqidcnetflow01` / `10.36.6.13`，Rocky Linux 8.10），重启服务失败。
* **报错信息**：
  ```text
  systemctl status flow-backend --no-pager
  Active: activating (auto-restart) (Result: exit-code)
  Process: 169261 ExecStart=/opt/flow-backend/bin/flow-server ... (code=exited, status=1/FAILURE)
  Main PID: 169261 (code=exited, status=1/FAILURE)
  ```

### 2. 深度根因分析
* **宿主机 glibc 版本不兼容**：
  编译机器（10.3.11.78）为 Ubuntu 24.04，系统自带 `glibc 2.38`。在执行 `go build` 时若未显式指定 `CGO_ENABLED=0`，Go 编译器默认开启 CGO，生成的二进制为动态链接：
  ```text
  dynamically linked, interpreter /lib64/ld-linux-x86-64.so.2, for GNU/Linux 3.2.0
  libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (glibc 2.38)
  ```
* 目标主机 `cqidcnetflow01` 是 **Rocky Linux 8.10**，系统自带的最高版本为 **`glibc 2.28`**。当动态链接器试图加载高版本 `GLIBC_2.32/2.34/2.38` 符号时失败，进程在进入 `main()` 之前便被内核直接终止（退出代码 status=1）。

### 3. 标准解决流程
必须执行**纯静态编译（Statically Linked）**，彻底切断对操作系统任何 glibc / 动态链接器的依赖：

```bash
# 纯静态编译命令（消除所有 C 运行库依赖）
CGO_ENABLED=0 go build -ldflags="-s -w" -o /opt/flow-backend/bin/flow-server ./cmd/server
```

* **编译验证**：执行 `file` 检查，必须输出 **`statically linked`**：
  ```text
  # file /opt/flow-backend/bin/flow-server
  /opt/flow-backend/bin/flow-server: ELF 64-bit LSB executable, x86-64, version 1 (SYSV), statically linked, stripped
  ```
* **兼容性保证**：纯静态编译的二进制可保证在任何 Linux 发行版（Rocky 8/9、CentOS 7/8、RHEL 8/9、Ubuntu、Debian、Alpine）上 100% 免依赖无缝运行。

---

## 生产环境极速平滑热升级 SOP

如果需要在其他已有主机上升级此版本，**无需重新运行安装脚本，无需动数据库与采集器**，只需 1 分钟即可完成热更新：

```bash
# ==========================================
# 步骤 1：本地电脑上传文件至目标主机 /tmp 目录
# ==========================================
scp d:/nTop/deploy/bin/flow-server root@<TARGET_IP>:/tmp/flow-server
scp d:/nTop/deploy/frontend/index.html root@<TARGET_IP>:/tmp/index.html
scp d:/nTop/deploy/config/default_test_config.json root@<TARGET_IP>:/tmp/default_test_config.json

# ==========================================
# 步骤 2：登录目标主机执行替换与重启
# ==========================================
mv /tmp/flow-server /opt/flow-backend/bin/flow-server
mv /tmp/index.html /opt/flow-backend/frontend/index.html
mkdir -p /opt/flow-backend/config
mv /tmp/default_test_config.json /opt/flow-backend/config/default_test_config.json
chmod +x /opt/flow-backend/bin/flow-server

# 平滑重启后端 API 服务
systemctl restart flow-backend
systemctl status flow-backend --no-pager
```
