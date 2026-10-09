#!/usr/bin/env python3
"""
Builder for Network View Reorganization:
- Network Tab:
  - Subtab 1: Subnets & Network Addressing Summary / Definition (IPAM)
  - Subtab 2: SNMP Device Hub (Hierarchical structure, custom attributes modal, IF-MIB interface tree)
- Settings Tab:
  - Cleaned up: App mappings + Security/System SLA monitoring
"""

import os

SRC_FILE = r"d:\nTop\frontend\index.html.bak"
OUT_FILE = r"d:\nTop\frontend\index.html"

with open(SRC_FILE, "r", encoding="utf-8") as f:
    lines = f.readlines()

# 1. Extract Head (lines 0 to 301, 1-indexed 1..302)
head_lines = lines[0:302]

# 2. Extract Dashboard (1-indexed lines 700..876) -> 0-indexed [699:876]
dashboard_block = "".join(lines[699:876])
dashboard_block = dashboard_block.replace(
    '<div v-show="activeMainView === \'global\'">',
    '<div v-show="activeNav === \'dashboard\'">'
)

# 3. Extract Monitor (1-indexed lines 347..467) -> 0-indexed [346:467]
monitor_block = "".join(lines[346:467])
monitor_block = monitor_block.replace(
    '<div v-show="deviceViewMode === \'list\'">',
    '<div v-show="activeNav === \'monitor\'">'
)

# 4. Extract Traffic Analysis (1-indexed lines 470..696) -> 0-indexed [469:696]
analysis_block = "".join(lines[469:696])
analysis_block = analysis_block.replace(
    '<div v-show="deviceViewMode === \'interface_detail\'">',
    '<div v-show="activeNav === \'traffic_analysis\'">'
)

new_analysis_hdr = """                    <!-- Analysis Header & Device/Interface Selector Bar -->
                    <div class="d-flex flex-wrap justify-content-between align-items-center mb-3 p-2 px-3 filter-card">
                        <div class="d-flex flex-wrap align-items-center gap-3">
                            <button class="btn btn-outline-secondary btn-sm fw-bold" @click="activeNav = 'monitor'" title="返回网络设备监控列表">
                                <i class="fas fa-arrow-left me-1"></i>返回设备监控
                            </button>
                            <div class="d-flex align-items-center gap-2">
                                <label class="small fw-bold" :style="{color: 'var(--text-muted)'}"><i class="fas fa-server text-info me-1"></i>分析设备:</label>
                                <select class="form-select form-select-sm" style="width: auto; min-width: 200px;" v-model="selectedAnalysisDeviceIp" @change="onAnalysisDeviceChange">
                                    <option v-for="dev in deviceOverviewList" :key="dev.exporter_ip" :value="dev.exporter_ip">
                                        {{ dev.device_name }} ({{ dev.exporter_ip }})
                                    </option>
                                </select>
                            </div>
                            <div class="d-flex align-items-center gap-2">
                                <label class="small fw-bold" :style="{color: 'var(--text-muted)'}"><i class="fas fa-network-wired text-primary me-1"></i>分析接口:</label>
                                <select class="form-select form-select-sm" style="width: auto; min-width: 230px;" v-model="selectedAnalysisIfIndex" @change="onAnalysisInterfaceChange">
                                    <option v-for="ifc in currentAnalysisDeviceInterfaces" :key="ifc.if_index" :value="ifc.if_index">
                                        #{{ ifc.if_index }} - {{ ifc.display_name }} {{ ifc.has_flow ? '🔥 [采样中]' : '' }}
                                    </option>
                                </select>
                            </div>
                        </div>
                        <div class="d-flex gap-2">
                            <button class="btn btn-sm btn-outline-info" @click="fetchInterfaceAnalytics" :disabled="ifaceSessionsLoading">
                                <i class="fas fa-sync-alt me-1" :class="{'fa-spin': ifaceSessionsLoading}"></i>刷新端口数据
                            </button>
                        </div>
                    </div>"""

p_hdr = analysis_block.find("<!-- Breadcrumbs Header -->")
p_kpi = analysis_block.find("<!-- Interface KPI Cards -->")
if p_hdr != -1 and p_kpi != -1:
    analysis_block = analysis_block[:p_hdr] + new_analysis_hdr + "\n\n" + analysis_block[p_kpi:]

# 5. Build New Network Block (Subnets & IPAM + Hierarchical SNMP Device Hub)
network_block = """                <!-- ==================== 4. 网络 (Network) ==================== -->
                <div v-show="activeNav === 'network'">
                    <!-- Top Network Sub Tabs: 网段与网络地址汇总与定义 VS SNMP 设备与探测管理 -->
                    <div class="card p-3 mb-3" style="background: var(--bg-card); border-color: var(--border-color);">
                        <ul class="nav nav-pills" id="networkSubTab" role="tablist">
                            <li class="nav-item me-2">
                                <button type="button" class="btn btn-sm" :class="networkSubTab === 'subnets' ? 'btn-primary' : 'btn-outline-secondary'" @click="networkSubTab = 'subnets'">
                                    <i class="fas fa-network-wired me-1"></i>网段与网络地址汇总与定义 (Subnets & IPAM)
                                </button>
                            </li>
                            <li class="nav-item">
                                <button type="button" class="btn btn-sm" :class="networkSubTab === 'snmp' ? 'btn-primary' : 'btn-outline-secondary'" @click="networkSubTab = 'snmp'">
                                    <i class="fas fa-satellite-dish me-1"></i>SNMP 设备配置与探测管理 (SNMP Device Hub)
                                </button>
                            </li>
                        </ul>
                    </div>

                    <!-- ==================== Sub-View A: 网段与网络地址汇总与定义 ==================== -->
                    <div v-show="networkSubTab === 'subnets'">
                        <!-- Subnet Overview KPIs -->
                        <div class="row g-3 mb-3">
                            <div class="col-md-3">
                                <div class="dashboard-card">
                                    <div class="card-title"><span>已定义业务网段</span><i class="fas fa-sitemap text-primary"></i></div>
                                    <div class="kpi-value text-primary">{{ subnetsSummaryList.length }} 个</div>
                                    <div class="small mt-1" :style="{color: 'var(--text-muted)'}">纳管 CIDR 网段空间</div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="dashboard-card">
                                    <div class="card-title"><span>全网活跃主机地址 (24h)</span><i class="fas fa-desktop text-success"></i></div>
                                    <div class="kpi-value text-success">{{ totalSubnetActiveIPs }} 个</div>
                                    <div class="small mt-1" :style="{color: 'var(--text-muted)'}">匹配流通信活跃主机数</div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="dashboard-card">
                                    <div class="card-title"><span>网段匹配总流量 (24h)</span><i class="fas fa-database text-info"></i></div>
                                    <div class="kpi-value text-info">{{ totalSubnetBytesFormatted }}</div>
                                    <div class="small mt-1" :style="{color: 'var(--text-muted)'}">业务子网累计吞吐量</div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="dashboard-card">
                                    <div class="card-title"><span>流量最高业务网段</span><i class="fas fa-chart-pie text-warning"></i></div>
                                    <div class="kpi-value text-warning" style="font-size: 1.15rem; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">{{ topSubnetName }}</div>
                                    <div class="small mt-1" :style="{color: 'var(--text-muted)'}">流量贡献占比: {{ topSubnetPct }}%</div>
                                </div>
                            </div>
                        </div>

                        <!-- Add / Define Business Subnet Card -->
                        <div class="card p-3 mb-3" style="background: var(--bg-body); border-color: var(--border-color);">
                            <div class="d-flex justify-content-between align-items-center mb-2">
                                <h6 class="fw-bold mb-0 small text-primary"><i class="fas fa-plus-circle me-1"></i>新增 / 定义业务部门子网 (CIDR IPAM)</h6>
                                <button class="btn btn-sm btn-outline-info py-0 px-2" @click="fetchSubnetsSummary" :disabled="subnetsLoading">
                                    <i class="fas fa-sync-alt me-1" :class="{'fa-spin': subnetsLoading}"></i>刷新网段统计
                                </button>
                            </div>
                            <div class="row g-2 align-items-center">
                                <div class="col-md-3">
                                    <input type="text" class="form-control form-control-sm" v-model="newGroup.group_name" placeholder="网段名称 (如: 研发中心服务器群)">
                                </div>
                                <div class="col-md-3">
                                    <input type="text" class="form-control form-control-sm" v-model="newGroup.cidr" placeholder="CIDR 网段范围 (如: 10.40.0.0/16)">
                                </div>
                                <div class="col-md-3">
                                    <input type="text" class="form-control form-control-sm" v-model="newGroup.department" placeholder="所属部门 / 业务组 (如: 研发中心)">
                                </div>
                                <div class="col-md-3">
                                    <button type="button" class="btn btn-sm btn-primary w-100" @click="saveBusinessGroup" :disabled="configLoading">
                                        <i class="fas fa-save me-1"></i>保存网段定义
                                    </button>
                                </div>
                            </div>
                        </div>

                        <!-- Subnets Table with Traffic Volume and Active IP Summary -->
                        <div class="card p-3 mb-3" style="background: var(--bg-card); border-color: var(--border-color);">
                            <h6 class="fw-bold mb-2 small" :style="{color: 'var(--text-main)'}"><i class="fas fa-list me-1 text-info"></i>已定义网段列表与流量汇总</h6>
                            <div class="table-responsive">
                                <table class="table top-table table-sm align-middle mb-0">
                                    <thead>
                                        <tr class="border-bottom" :style="{borderColor: 'var(--border-color)', color: 'var(--text-muted)'}">
                                            <th style="width: 60px;">ID</th>
                                            <th>网段名称</th>
                                            <th>CIDR 网段范围</th>
                                            <th>归属部门</th>
                                            <th class="text-end">24h 流量</th>
                                            <th style="width: 140px;">流量占比</th>
                                            <th class="text-end">活跃主机数</th>
                                            <th class="text-end" style="width: 100px;">操作</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr v-for="bg in subnetsSummaryList" :key="bg.group_id">
                                            <td><span class="badge bg-secondary">{{ bg.group_id }}</span></td>
                                            <td class="fw-bold">{{ bg.group_name }}</td>
                                            <td><span class="badge bg-dark font-monospace border border-secondary text-info">{{ bg.cidr }}</span></td>
                                            <td :style="{color: 'var(--text-muted)'}">{{ bg.department }}</td>
                                            <td class="text-end font-monospace text-info fw-bold">{{ bg.formatted_bytes }}</td>
                                            <td>
                                                <div class="d-flex align-items-center gap-2">
                                                    <div class="progress flex-grow-1" style="height: 6px; background: rgba(255,255,255,0.1);">
                                                        <div class="progress-bar bg-primary" :style="{width: (bg.percentage || 0) + '%'}"></div>
                                                    </div>
                                                    <span class="small font-monospace text-secondary" style="font-size: 0.75rem;">{{ bg.percentage || 0 }}%</span>
                                                </div>
                                            </td>
                                            <td class="text-end font-monospace text-success fw-bold">{{ bg.active_ip_count }} 台</td>
                                            <td class="text-end">
                                                <button type="button" class="btn btn-outline-danger btn-sm py-0 px-2" @click="deleteBusinessGroup(bg.group_id)" title="删除此网段定义">
                                                    <i class="fas fa-trash-alt"></i>
                                                </button>
                                            </td>
                                        </tr>
                                        <tr v-if="subnetsSummaryList.length === 0">
                                            <td colspan="8" class="text-center py-4" :style="{color: 'var(--text-muted)'}">
                                                <span v-if="subnetsLoading"><i class="fas fa-spinner fa-spin me-2"></i>正在加载网段数据...</span>
                                                <span v-else>暂无配置网段定义</span>
                                            </td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        <!-- Network Address Summary: Top Active Host IPs with Subnet Tagging -->
                        <div class="card p-3" style="background: var(--bg-card); border-color: var(--border-color);">
                            <div class="d-flex justify-content-between align-items-center mb-2">
                                <h6 class="fw-bold mb-0 small" :style="{color: 'var(--text-main)'}">
                                    <i class="fas fa-stream me-1 text-success"></i>全网活跃网络地址汇总与归属分析 (Active Host Addresses)
                                </h6>
                                <span class="small" :style="{color: 'var(--text-muted)'}">基于全网真实 NetFlow 采集自动解析归集</span>
                            </div>
                            <div class="table-responsive" style="max-height: 360px; overflow-y: auto;">
                                <table class="table top-table table-sm align-middle mb-0">
                                    <thead>
                                        <tr class="border-bottom" :style="{borderColor: 'var(--border-color)', color: 'var(--text-muted)'}">
                                            <th style="width: 50px;">#</th>
                                            <th>主机网络地址 (IP)</th>
                                            <th>匹配归属网段</th>
                                            <th>采集关联设备 / 接口</th>
                                            <th class="text-end">24h 流量</th>
                                            <th class="text-end">全网占比</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr v-for="(item, idx) in topItems" :key="idx">
                                            <td><span class="badge" :class="isDark ? 'bg-secondary' : 'bg-light text-dark border'">{{ idx + 1 }}</span></td>
                                            <td><span class="fw-bold font-monospace ip-address-text text-info">{{ item.key }}</span></td>
                                            <td>
                                                <span class="badge bg-dark border border-primary text-info font-monospace">{{ resolveSubnetForIP(item.key) }}</span>
                                            </td>
                                            <td><span class="small text-secondary">{{ item.label }}</span></td>
                                            <td class="text-end font-monospace text-primary fw-bold">{{ item.formatted }}</td>
                                            <td class="text-end font-monospace text-secondary">{{ item.percentage }}%</td>
                                        </tr>
                                        <tr v-if="topItems.length === 0">
                                            <td colspan="6" class="text-center py-4" :style="{color: 'var(--text-muted)'}">暂无活跃地址流记录</td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>

                    <!-- ==================== Sub-View B: SNMP 设备配置与探测管理 (层次化) ==================== -->
                    <div v-show="networkSubTab === 'snmp'">
                        <!-- Layer 1: 全局 SNMP 探测与自动发现工具栏 -->
                        <div class="card p-3 mb-3" style="background: var(--bg-body); border: 1px solid #0284c7;">
                            <div class="d-flex justify-content-between align-items-center mb-2">
                                <h6 class="fw-bold mb-0 small text-info"><i class="fas fa-satellite-dish me-1"></i>通过 SNMP 自动获取设备名称与信息 (sysName.0 / IF-MIB)</h6>
                                <span class="badge bg-info-subtle text-info border border-info px-2 py-1">RFC 1213 / RFC 2863 标准</span>
                            </div>
                            <div class="row g-2 align-items-center">
                                <div class="col-md-3">
                                    <label class="form-label small mb-1" :style="{color: 'var(--text-muted)'}">设备 Exporter IP</label>
                                    <input type="text" class="form-control form-control-sm" v-model="snmpProbeForm.exporter_ip" placeholder="如 10.23.251.238">
                                </div>
                                <div class="col-md-3">
                                    <label class="form-label small mb-1" :style="{color: 'var(--text-muted)'}">SNMP Community 团体名</label>
                                    <input type="text" class="form-control form-control-sm" v-model="snmpProbeForm.community" placeholder="如 y35eaG63W64W 或 public">
                                </div>
                                <div class="col-md-2">
                                    <label class="form-label small mb-1" :style="{color: 'var(--text-muted)'}">SNMP 版本</label>
                                    <select class="form-select form-select-sm" v-model="snmpProbeForm.version">
                                        <option value="2c">SNMP v2c</option>
                                        <option value="1">SNMP v1</option>
                                        <option value="3">SNMP v3</option>
                                    </select>
                                </div>
                                <div class="col-md-4 d-flex gap-2 align-items-end">
                                    <button type="button" class="btn btn-sm btn-info text-white flex-grow-1" @click="probeSNMP(snmpProbeForm.exporter_ip, snmpProbeForm.community, snmpProbeForm.version)" :disabled="snmpLoading">
                                        <i class="fas" :class="snmpLoading ? 'fa-spinner fa-spin' : 'fa-bolt'"></i>
                                        <span class="ms-1">{{ snmpLoading ? '探测中...' : '⚡ 探测单机' }}</span>
                                    </button>
                                    <button type="button" class="btn btn-sm btn-success text-white" @click="syncAllSNMP" :disabled="snmpLoading || snmpAllLoading" title="使用当前团体名批量探测并更新全网所有 Exporter 设备名称">
                                        <i class="fas" :class="snmpAllLoading ? 'fa-spinner fa-spin' : 'fa-network-wired'"></i>
                                        <span class="ms-1">{{ snmpAllLoading ? '同步中...' : '⚡ 全网批量同步' }}</span>
                                    </button>
                                </div>
                            </div>
                            <!-- Feedback msg -->
                            <div v-if="snmpResult.show" class="mt-2 p-2 rounded small" :class="snmpResult.success ? 'bg-success-subtle text-success border border-success' : 'bg-warning-subtle text-warning border border-warning'">
                                <i class="fas" :class="snmpResult.success ? 'fa-check-circle me-1' : 'fa-exclamation-triangle me-1'"></i>
                                <strong>{{ snmpResult.title }}:</strong> {{ snmpResult.msg }}
                            </div>
                        </div>

                        <!-- Layer 2: 托管物理网络设备列表与自定义属性 -->
                        <div class="card p-3 mb-3" style="background: var(--bg-card); border-color: var(--border-color);">
                            <div class="d-flex justify-content-between align-items-center mb-3">
                                <div>
                                    <h6 class="fw-bold mb-1" :style="{color: 'var(--text-main)'}"><i class="fas fa-server me-1 text-primary"></i>托管网络设备清单与自定义属性中心</h6>
                                    <div class="small" :style="{color: 'var(--text-muted)'}">支持自定义设备类型、机房机柜物理位置、运维责任人及独立专属 SNMP 团体名；点击【编辑属性】可随时调整。</div>
                                </div>
                                <button class="btn btn-sm btn-outline-primary" @click="openNewDeviceModal">
                                    <i class="fas fa-plus me-1"></i>手动录入设备
                                </button>
                            </div>

                            <div class="table-responsive">
                                <table class="table top-table table-sm align-middle mb-0">
                                    <thead>
                                        <tr class="border-bottom" :style="{borderColor: 'var(--border-color)', color: 'var(--text-muted)'}">
                                            <th>管理 IP</th>
                                            <th>设备显示名称</th>
                                            <th>设备类型</th>
                                            <th>物理机房 / 位置</th>
                                            <th>运维责任人</th>
                                            <th>SNMP 状态</th>
                                            <th>描述 / 业务说明</th>
                                            <th class="text-end" style="width: 220px;">操作</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr v-for="dev in exporterList" :key="dev.exporter_ip">
                                            <td><span class="fw-bold font-monospace text-info">{{ dev.exporter_ip }}</span></td>
                                            <td class="fw-bold">{{ dev.device_name }}</td>
                                            <td>
                                                <span class="badge" :class="getDeviceTypeBadgeClass(dev.device_type)">{{ dev.device_type || 'Switch' }}</span>
                                            </td>
                                            <td>
                                                <span v-if="dev.location" class="badge bg-secondary font-monospace"><i class="fas fa-map-marker-alt me-1 text-warning"></i>{{ dev.location }}</span>
                                                <span v-else class="text-muted small">--</span>
                                            </td>
                                            <td>
                                                <span v-if="dev.admin" class="small text-light"><i class="fas fa-user-shield me-1 text-info"></i>{{ dev.admin }}</span>
                                                <span v-else class="text-muted small">未指定</span>
                                            </td>
                                            <td>
                                                <span class="badge bg-dark border border-secondary text-secondary font-monospace">
                                                    {{ dev.snmp_version || '2c' }} {{ dev.snmp_community ? '(专属)' : '(默认)' }}
                                                </span>
                                            </td>
                                            <td class="small" :style="{color: 'var(--text-muted)'}">{{ dev.description }}</td>
                                            <td class="text-end">
                                                <div class="btn-group btn-group-sm">
                                                    <button type="button" class="btn btn-outline-warning py-0 px-2" @click="editDeviceAttributes(dev)" title="自定义编辑设备属性 (名称、类型、机房、责任人等)">
                                                        <i class="fas fa-edit"></i> 编辑属性
                                                    </button>
                                                    <button type="button" class="btn btn-outline-primary py-0 px-2" @click="selectDeviceForInterface(dev.exporter_ip)" :class="{'active': selectedExporterIp === dev.exporter_ip}" title="管理此设备的物理接口描述与别名">
                                                        <i class="fas fa-plug"></i> 端口映射
                                                    </button>
                                                    <button type="button" class="btn btn-outline-info py-0 px-2" @click="probeSNMP(dev.exporter_ip, dev.snmp_community || snmpProbeForm.community, dev.snmp_version || snmpProbeForm.version)" :disabled="snmpLoading" title="使用 SNMP 重新同步此设备">
                                                        <i class="fas fa-sync-alt" :class="{'fa-spin': snmpLoading && snmpProbeForm.exporter_ip === dev.exporter_ip}"></i>
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        <!-- Layer 4: 下挂物理/逻辑端口与 IF-MIB 映射面板 (选中某台设备后显示) -->
                        <div v-if="selectedExporterIp" class="card p-3" style="background: var(--bg-body); border-color: var(--border-color);">
                            <div class="d-flex flex-wrap justify-content-between align-items-center mb-3">
                                <div class="d-flex align-items-center gap-2">
                                    <h6 class="fw-bold mb-0 small text-primary"><i class="fas fa-plug me-1"></i>设备接口定义与 SNMP 端口描述管理 (Interface Mapping)</h6>
                                    <span class="badge bg-primary-subtle text-primary border border-primary px-2">RFC 2863 IF-MIB</span>
                                    <span class="badge bg-dark border border-secondary text-info font-monospace">{{ selectedExporterIp }}</span>
                                </div>
                                <div class="d-flex align-items-center gap-2">
                                    <button type="button" class="btn btn-sm btn-outline-primary py-1 px-2" @click="loadDeviceInterfaces(selectedExporterIp)" title="刷新端口列表">
                                        <i class="fas fa-sync-alt"></i>
                                    </button>
                                    <button type="button" class="btn btn-sm btn-primary" @click="walkSNMPInterfaces(selectedExporterIp)" :disabled="snmpIfLoading">
                                        <i class="fas" :class="snmpIfLoading ? 'fa-spinner fa-spin' : 'fa-bolt'"></i>
                                        <span class="ms-1">{{ snmpIfLoading ? '同步中...' : '⚡ SNMP 同步接口描述' }}</span>
                                    </button>
                                </div>
                            </div>

                            <!-- 设备 SNMP 详情状态卡片 -->
                            <div v-if="deviceSnmpDetails && deviceSnmpDetails[selectedExporterIp]" class="p-2 mb-2 rounded small border" style="background: rgba(59, 130, 246, 0.05); border-color: rgba(59, 130, 246, 0.3) !important;">
                                <div class="row g-2">
                                    <div class="col-md-3"><strong>系统名称:</strong> {{ deviceSnmpDetails[selectedExporterIp].sys_name }}</div>
                                    <div class="col-md-3"><strong>设备类型:</strong> <span class="badge bg-secondary">{{ deviceSnmpDetails[selectedExporterIp].device_type }}</span></div>
                                    <div class="col-md-3"><strong>运行时间:</strong> {{ deviceSnmpDetails[selectedExporterIp].sys_uptime || 'N/A' }}</div>
                                    <div class="col-md-3"><strong>物理位置:</strong> {{ deviceSnmpDetails[selectedExporterIp].sys_location || '核心机房' }}</div>
                                    <div class="col-12 text-truncate" :title="deviceSnmpDetails[selectedExporterIp].sys_descr">
                                        <strong>硬件与系统描述:</strong> <span class="text-muted">{{ deviceSnmpDetails[selectedExporterIp].sys_descr }}</span>
                                    </div>
                                </div>
                            </div>

                            <div class="table-responsive" style="max-height: 420px; overflow-y: auto;">
                                <table class="table top-table table-sm align-middle mb-0">
                                    <thead>
                                        <tr class="border-bottom" :style="{borderColor: 'var(--border-color)', color: 'var(--text-muted)'}">
                                            <th style="width: 70px;">ifIndex</th>
                                            <th style="width: 130px;">SNMP端口名</th>
                                            <th>SNMP 描述 / Alias</th>
                                            <th>当前生效接口显示名 (支持修改)</th>
                                            <th style="width: 100px;">速率</th>
                                            <th class="text-end" style="width: 90px;">操作</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr v-for="ifc in currentInterfaces" :key="ifc.if_index">
                                            <td><span class="badge bg-secondary">#{{ ifc.if_index }}</span></td>
                                            <td class="font-monospace fw-bold">{{ ifc.if_name }}</td>
                                            <td>
                                                <span v-if="ifc.if_alias" class="badge bg-dark border border-info text-info"><i class="fas fa-tag me-1"></i>{{ ifc.if_alias }}</span>
                                                <span v-else class="text-muted small">{{ ifc.if_descr }}</span>
                                            </td>
                                            <td>
                                                <input type="text" class="form-control form-control-sm font-monospace" v-model="ifc.display_name" placeholder="自定义接口显示名 (如 port1 (WAN1))">
                                            </td>
                                            <td><span class="badge bg-secondary font-monospace">{{ ifc.speed_mbps }} Mbps</span></td>
                                            <td class="text-end">
                                                <button type="button" class="btn btn-sm btn-outline-success py-0 px-2" @click="saveInterface(ifc)" :disabled="ifSaving && ifSaving[ifc.if_index]">
                                                    <i class="fas fa-save me-1"></i>保存
                                                </button>
                                            </td>
                                        </tr>
                                        <tr v-if="!currentInterfaces || currentInterfaces.length === 0">
                                            <td colspan="6" class="text-center py-4" :style="{color: 'var(--text-muted)'}">
                                                <span v-if="snmpIfLoading"><i class="fas fa-spinner fa-spin me-2"></i>正在加载接口列表...</span>
                                                <span v-else>暂无该设备的接口映射记录，请点击上方【⚡ SNMP 同步接口描述】自动拉取</span>
                                            </td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </div>"""

# 6. Build Clean Settings Block (Only App Mappings + Safety & System SLA)
apps_block = "".join(lines[963:1011])
apps_block = apps_block.replace(
    '<div class="tab-pane fade" id="tab-apps" role="tabpanel">',
    '<div v-show="settingsSubTab === \'apps\'">'
)

system_block = "".join(lines[1192:1237])
system_block = system_block.replace(
    '<div class="tab-pane fade" id="tab-system" role="tabpanel">',
    '<div v-show="settingsSubTab === \'system\'">'
)

settings_block = f"""                <!-- ==================== 5. 设置 (Settings) ==================== -->
                <div v-show="activeNav === 'settings'">
                    <!-- Settings Sub Tabs Navigation -->
                    <div class="card p-3 mb-3" style="background: var(--bg-card); border-color: var(--border-color);">
                        <ul class="nav nav-pills" id="settingsSubTab" role="tablist">
                            <li class="nav-item me-2">
                                <button type="button" class="btn btn-sm" :class="settingsSubTab === 'apps' ? 'btn-primary' : 'btn-outline-secondary'" @click="settingsSubTab = 'apps'">
                                    <i class="fas fa-network-wired me-1"></i>应用端口字典映射
                                </button>
                            </li>
                            <li class="nav-item">
                                <button type="button" class="btn btn-sm" :class="settingsSubTab === 'system' ? 'btn-primary' : 'btn-outline-secondary'" @click="settingsSubTab = 'system'">
                                    <i class="fas fa-shield-alt me-1"></i>安全告警与系统健康监控
                                </button>
                            </li>
                        </ul>
                    </div>

                    {apps_block}
                    {system_block}
                </div>"""

# 7. Device Custom Attribute Edit Modal (Layer 3)
device_edit_modal = """
    <!-- Device Custom Attribute Edit Modal -->
    <div class="modal fade" id="deviceEditModal" tabindex="-1" aria-hidden="true">
        <div class="modal-dialog modal-lg modal-dialog-centered">
            <div class="modal-content" style="background: var(--bg-card); border: 1px solid var(--border-color); color: var(--text-main);">
                <div class="modal-header py-2 px-3 border-bottom" :style="{borderColor: 'var(--border-color)'}">
                    <h6 class="modal-title fw-bold text-primary d-flex align-items-center gap-2">
                        <i class="fas fa-sliders-h"></i>
                        <span>自定义设备运维属性: {{ editingDevice.exporter_ip }}</span>
                    </h6>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body p-3">
                    <div class="row g-3">
                        <div class="col-md-6">
                            <label class="form-label small fw-bold" :style="{color: 'var(--text-muted)'}">设备 IP / Exporter IP</label>
                            <input type="text" class="form-control form-control-sm font-monospace" v-model="editingDevice.exporter_ip" :disabled="!isNewDevice" placeholder="如 10.23.251.238">
                        </div>
                        <div class="col-md-6">
                            <label class="form-label small fw-bold" :style="{color: 'var(--text-muted)'}">设备显示名称 (自定义标识)</label>
                            <input type="text" class="form-control form-control-sm" v-model="editingDevice.device_name" placeholder="如: 出口主防火墙 FortiGate-200F">
                        </div>
                        <div class="col-md-6">
                            <label class="form-label small fw-bold" :style="{color: 'var(--text-muted)'}">设备类型</label>
                            <select class="form-select form-select-sm" v-model="editingDevice.device_type">
                                <option value="Firewall">防火墙 (Firewall)</option>
                                <option value="Core Switch">核心交换机 (Core Switch)</option>
                                <option value="Switch">普通交换机 (Switch)</option>
                                <option value="Aggregation Switch">汇聚交换机 (Aggregation Switch)</option>
                                <option value="Access Switch">接入交换机 (Access Switch)</option>
                                <option value="Router">路由器 (Router)</option>
                                <option value="Load Balancer">负载均衡 (Load Balancer)</option>
                                <option value="Server">服务器 (Server)</option>
                                <option value="Other">其他网络设备 (Other)</option>
                            </select>
                        </div>
                        <div class="col-md-6">
                            <label class="form-label small fw-bold" :style="{color: 'var(--text-muted)'}">物理机房 / 机柜位置</label>
                            <input type="text" class="form-control form-control-sm" v-model="editingDevice.location" placeholder="如: 张江数据中心 DC-A01 机柜">
                        </div>
                        <div class="col-md-6">
                            <label class="form-label small fw-bold" :style="{color: 'var(--text-muted)'}">运维负责团队 / 联系人</label>
                            <input type="text" class="form-control form-control-sm" v-model="editingDevice.admin" placeholder="如: 网络运维组 - 王工 (ext. 8820)">
                        </div>
                        <div class="col-md-4">
                            <label class="form-label small fw-bold" :style="{color: 'var(--text-muted)'}">专属 SNMP Community 团体名</label>
                            <input type="text" class="form-control form-control-sm" v-model="editingDevice.snmp_community" placeholder="留空则使用全局默认团体名">
                        </div>
                        <div class="col-md-2">
                            <label class="form-label small fw-bold" :style="{color: 'var(--text-muted)'}">SNMP 版本</label>
                            <select class="form-select form-select-sm" v-model="editingDevice.snmp_version">
                                <option value="2c">v2c</option>
                                <option value="1">v1</option>
                                <option value="3">v3</option>
                            </select>
                        </div>
                        <div class="col-12">
                            <label class="form-label small fw-bold" :style="{color: 'var(--text-muted)'}">设备描述 / 业务用途说明</label>
                            <textarea class="form-control form-control-sm" rows="2" v-model="editingDevice.description" placeholder="记录设备的主要业务承载、冗余状态或维护说明"></textarea>
                        </div>
                    </div>
                </div>
                <div class="modal-footer py-2 px-3 border-top" :style="{borderColor: 'var(--border-color)'}">
                    <button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">取消</button>
                    <button type="button" class="btn btn-primary btn-sm px-3" @click="saveDeviceCustomAttributes" :disabled="configLoading">
                        <i class="fas fa-save me-1"></i>保存设备属性
                    </button>
                </div>
            </div>
        </div>
    </div>
"""

# 8. Layout HTML Body
html_body = f"""<body>
    <div id="app" :class="isDark ? '' : 'theme-light'" class="app-layout">
        <!-- ==================== Left Sidebar ==================== -->
        <aside class="app-sidebar">
            <div class="sidebar-brand">
                <i class="fas fa-cubes text-primary fs-4"></i>
                <div class="d-flex flex-column">
                    <span class="fw-bold fs-6 lh-1" :style="{{color: 'var(--text-main)'}}">NetFlow Pro</span>
                    <span class="text-secondary" style="font-size: 0.65rem; margin-top: 3px;">流量智能分析平台</span>
                </div>
            </div>

            <!-- Flat Navigation: 仪表盘 / 监控 / 流量分析 / 网络 / 设置 -->
            <div class="sidebar-menu">
                <button type="button" class="sidebar-btn" :class="{{ active: activeNav === 'dashboard' }}" @click="switchNav('dashboard')">
                    <i class="fas fa-chart-pie"></i>
                    <span>仪表盘</span>
                </button>
                <button type="button" class="sidebar-btn" :class="{{ active: activeNav === 'monitor' }}" @click="switchNav('monitor')">
                    <i class="fas fa-desktop"></i>
                    <span>监控</span>
                </button>
                <button type="button" class="sidebar-btn" :class="{{ active: activeNav === 'traffic_analysis' }}" @click="switchNav('traffic_analysis')">
                    <i class="fas fa-chart-line"></i>
                    <span>流量分析</span>
                </button>
                <button type="button" class="sidebar-btn" :class="{{ active: activeNav === 'network' }}" @click="switchNav('network')">
                    <i class="fas fa-network-wired"></i>
                    <span>网络</span>
                </button>
                <button type="button" class="sidebar-btn" :class="{{ active: activeNav === 'settings' }}" @click="switchNav('settings')">
                    <i class="fas fa-sliders-h"></i>
                    <span>设置</span>
                </button>
            </div>

            <!-- Sidebar Bottom Info -->
            <div class="p-3 border-top small" :style="{{borderColor: 'var(--border-color)', color: 'var(--text-muted)'}}">
                <div class="d-flex align-items-center justify-content-between mb-1">
                    <span>系统状态</span>
                    <span class="badge bg-success small"><i class="fas fa-check-circle me-1"></i>在线</span>
                </div>
                <div class="font-monospace" style="font-size: 0.7rem;">ClickHouse + ntopng</div>
            </div>
        </aside>

        <!-- ==================== Right Main Viewport Area ==================== -->
        <main class="app-main">
            <!-- App Top Header Bar -->
            <header class="app-topbar">
                <div class="d-flex align-items-center gap-3">
                    <h6 class="mb-0 fw-bold d-flex align-items-center gap-2" :style="{{color: 'var(--text-main)'}}">
                        <span v-if="activeNav === 'dashboard'"><i class="fas fa-chart-pie text-primary me-1"></i>全网宏观流量仪表盘</span>
                        <span v-else-if="activeNav === 'monitor'"><i class="fas fa-desktop text-primary me-1"></i>网络物理设备与采样端口监控</span>
                        <span v-else-if="activeNav === 'traffic_analysis'"><i class="fas fa-chart-line text-primary me-1"></i>接口专属深度流分析工作台</span>
                        <span v-else-if="activeNav === 'network'"><i class="fas fa-network-wired text-primary me-1"></i>网段地址汇总与 SNMP 设备管理</span>
                        <span v-else-if="activeNav === 'settings'"><i class="fas fa-sliders-h text-primary me-1"></i>应用协议字典与系统 SLA 监控</span>
                    </h6>
                    <span class="badge-source ms-2"><i class="fas fa-database me-1"></i>{{{{ dataSourceLabel }}}}</span>
                </div>

                <div class="d-flex align-items-center gap-3">
                    <!-- Theme Mode Toggle -->
                    <button type="button" class="btn btn-sm d-flex align-items-center gap-1" :class="isDark ? 'btn-outline-warning' : 'btn-outline-primary'" @click="toggleTheme" title="切换白天/夜间显示模式">
                        <i class="fas" :class="isDark ? 'fa-sun text-warning' : 'fa-moon text-primary'"></i>
                        <span class="fw-bold" style="font-size: 0.8rem;">{{{{ isDark ? '白天模式' : '夜间模式' }}}}</span>
                    </button>
                    <!-- Refresh Button -->
                    <span class="small" :style="{{color: 'var(--text-muted)'}}"><i class="fas fa-clock me-1"></i>最后刷新: {{{{ lastRefreshTime }}}}</span>
                    <button class="btn btn-outline-primary btn-sm" @click="refreshCurrentNav" :disabled="loading || deviceOverviewLoading">
                        <i class="fas fa-sync-alt" :class="{{'fa-spin': loading || deviceOverviewLoading}}"></i> 刷新数据
                    </button>
                </div>
            </header>

            <!-- Scrollable Content Viewport -->
            <div class="app-content">
                <!-- ==================== 1. 仪表盘 (Dashboard) ==================== -->
                {dashboard_block}

                <!-- ==================== 2. 监控 (Monitor) ==================== -->
                {monitor_block}

                <!-- ==================== 3. 流量分析 (Traffic Analysis) ==================== -->
                {analysis_block}

                {network_block}

                {settings_block}
            </div>
        </main>
        {device_edit_modal}
    </div>
"""

# 9. Extract Script area (from line 1248 which is <script>)
script_lines = lines[1248:]
script_content = "".join(script_lines)

# Vue updates
script_content = script_content.replace(
    "const { createApp, ref, onMounted, nextTick } = Vue;",
    "const { createApp, ref, computed, onMounted, nextTick } = Vue;"
)

old_states_decl = "const activeMainView = ref('devices'); // 'devices' (Default) or 'global'\n                const deviceViewMode = ref('list'); // 'list' or 'interface_detail'"
new_states_decl = """const activeNav = ref('dashboard'); // 'dashboard', 'monitor', 'traffic_analysis', 'network', 'settings'
                const networkSubTab = ref('subnets'); // 'subnets' (网段与地址汇总), 'snmp' (SNMP 设备管理)
                const settingsSubTab = ref('apps'); // 'apps', 'system'
                const selectedAnalysisDeviceIp = ref('');
                const selectedAnalysisIfIndex = ref(null);

                // Subnets IPAM states
                const subnetsSummaryList = ref([]);
                const subnetsLoading = ref(false);

                // Device Custom Attribute Edit states
                const editingDevice = ref({
                    exporter_ip: '',
                    device_name: '',
                    device_type: 'Switch',
                    location: '',
                    admin: '',
                    snmp_community: '',
                    snmp_version: '2c',
                    description: ''
                });
                const isNewDevice = ref(false);
                let deviceEditModalInstance = null;

                const totalSubnetActiveIPs = computed(() => {
                    return subnetsSummaryList.value.reduce((sum, item) => sum + (item.active_ip_count || 0), 0);
                });

                const totalSubnetBytesFormatted = computed(() => {
                    const totalBytes = subnetsSummaryList.value.reduce((sum, item) => sum + (item.bytes || 0), 0);
                    return formatBytes(totalBytes);
                });

                const topSubnetName = computed(() => {
                    if (subnetsSummaryList.value.length === 0) return '--';
                    const sorted = [...subnetsSummaryList.value].sort((a, b) => (b.bytes || 0) - (a.bytes || 0));
                    return sorted[0].group_name;
                });

                const topSubnetPct = computed(() => {
                    if (subnetsSummaryList.value.length === 0) return 0;
                    const sorted = [...subnetsSummaryList.value].sort((a, b) => (b.bytes || 0) - (a.bytes || 0));
                    return sorted[0].percentage || 0;
                });

                function resolveSubnetForIP(ip) {
                    if (!ip) return '--';
                    for (const s of subnetsSummaryList.value) {
                        if (s.cidr && isIpInCidr(ip, s.cidr)) {
                            return s.group_name;
                        }
                    }
                    return '未分类外部网络';
                }

                function isIpInCidr(ip, cidr) {
                    try {
                        const [range, bits = 32] = cidr.split('/');
                        const mask = ~(2 ** (32 - Number(bits)) - 1);
                        const ipToLong = (ipAddr) => ipAddr.split('.').reduce((acc, oct) => (acc << 8) + Number(oct), 0) >>> 0;
                        return (ipToLong(ip) & mask) === (ipToLong(range) & mask);
                    } catch (e) {
                        return false;
                    }
                }

                function getDeviceTypeBadgeClass(type) {
                    const t = (type || '').toLowerCase();
                    if (t.includes('firewall') || t.includes('forti')) return 'bg-danger';
                    if (t.includes('core')) return 'bg-warning text-dark';
                    if (t.includes('switch')) return 'bg-primary';
                    if (t.includes('router')) return 'bg-info text-dark';
                    if (t.includes('server')) return 'bg-success';
                    return 'bg-secondary';
                }

                async function fetchSubnetsSummary() {
                    subnetsLoading.value = true;
                    try {
                        const res = await fetch(`${apiBase}/config/subnets-summary`).then(r => r.json());
                        if (res.code === 0) {
                            subnetsSummaryList.value = res.data || [];
                        }
                    } catch (e) {
                        console.error('Failed to load subnets summary:', e);
                    } finally {
                        subnetsLoading.value = false;
                    }
                }

                function openNewDeviceModal() {
                    isNewDevice.value = true;
                    editingDevice.value = {
                        exporter_ip: '',
                        device_name: '',
                        device_type: 'Switch',
                        location: '',
                        admin: '',
                        snmp_community: '',
                        snmp_version: '2c',
                        description: ''
                    };
                    if (!deviceEditModalInstance) {
                        deviceEditModalInstance = new bootstrap.Modal(document.getElementById('deviceEditModal'));
                    }
                    deviceEditModalInstance.show();
                }

                function editDeviceAttributes(dev) {
                    isNewDevice.value = false;
                    editingDevice.value = {
                        exporter_ip: dev.exporter_ip,
                        device_name: dev.device_name || '',
                        device_type: dev.device_type || 'Switch',
                        location: dev.location || '',
                        admin: dev.admin || '',
                        snmp_community: dev.snmp_community || '',
                        snmp_version: dev.snmp_version || '2c',
                        description: dev.description || ''
                    };
                    if (!deviceEditModalInstance) {
                        deviceEditModalInstance = new bootstrap.Modal(document.getElementById('deviceEditModal'));
                    }
                    deviceEditModalInstance.show();
                }

                async function saveDeviceCustomAttributes() {
                    if (!editingDevice.value.exporter_ip || !editingDevice.value.device_name) {
                        alert('请填写设备 IP 与显示名称！');
                        return;
                    }
                    configLoading.value = true;
                    try {
                        const res = await fetch(`${apiBase}/config/exporters`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(editingDevice.value)
                        }).then(r => r.json());
                        if (res.code === 0) {
                            if (deviceEditModalInstance) deviceEditModalInstance.hide();
                            await fetchConfigs();
                            await fetchDeviceOverview();
                            alert('设备自定义属性已保存生效！');
                        } else {
                            alert('保存失败: ' + res.message);
                        }
                    } catch (e) {
                        alert('网络错误: ' + e);
                    } finally {
                        configLoading.value = false;
                    }
                }

                const currentAnalysisDeviceInterfaces = computed(() => {
                    const dev = deviceOverviewList.value.find(d => d.exporter_ip === selectedAnalysisDeviceIp.value);
                    return dev ? (dev.interfaces || []) : [];
                });

                function onAnalysisDeviceChange() {
                    const dev = deviceOverviewList.value.find(d => d.exporter_ip === selectedAnalysisDeviceIp.value);
                    if (dev && dev.interfaces && dev.interfaces.length > 0) {
                        const samplingIf = dev.interfaces.find(i => i.has_flow);
                        const targetIf = samplingIf || dev.interfaces[0];
                        selectedAnalysisIfIndex.value = targetIf.if_index;
                        currentSelectedDevice.value = dev;
                        currentSelectedInterface.value = targetIf;
                    }
                    fetchInterfaceAnalytics();
                }

                function onAnalysisInterfaceChange() {
                    const dev = deviceOverviewList.value.find(d => d.exporter_ip === selectedAnalysisDeviceIp.value);
                    if (dev && dev.interfaces) {
                        const targetIf = dev.interfaces.find(i => i.if_index === Number(selectedAnalysisIfIndex.value));
                        if (targetIf) {
                            currentSelectedDevice.value = dev;
                            currentSelectedInterface.value = targetIf;
                        }
                    }
                    fetchInterfaceAnalytics();
                }

                function initAnalysisSelection() {
                    if (!selectedAnalysisDeviceIp.value && deviceOverviewList.value.length > 0) {
                        const dev = deviceOverviewList.value[0];
                        selectedAnalysisDeviceIp.value = dev.exporter_ip;
                        currentSelectedDevice.value = dev;
                        if (dev.interfaces && dev.interfaces.length > 0) {
                            const samplingIf = dev.interfaces.find(i => i.has_flow);
                            const targetIf = samplingIf || dev.interfaces[0];
                            selectedAnalysisIfIndex.value = targetIf.if_index;
                            currentSelectedInterface.value = targetIf;
                        }
                    }
                }

                function switchNav(nav) {
                    activeNav.value = nav;
                    nextTick(() => {
                        if (nav === 'dashboard') {
                            if (window.trendChartInstance) window.trendChartInstance.resize();
                            if (window.sankeyChartInstance) window.sankeyChartInstance.resize();
                        } else if (nav === 'traffic_analysis') {
                            initAnalysisSelection();
                            if (window.ifaceTrendChartInstance) {
                                window.ifaceTrendChartInstance.resize();
                            } else {
                                fetchInterfaceAnalytics();
                            }
                        } else if (nav === 'network') {
                            fetchConfigs();
                            fetchSubnetsSummary();
                            if (exporterList.value.length > 0 && !selectedExporterIp.value) {
                                selectDeviceForInterface(exporterList.value[0].exporter_ip);
                            }
                        } else if (nav === 'settings') {
                            fetchConfigs();
                        }
                    });
                }

                function refreshCurrentNav() {
                    if (activeNav.value === 'dashboard') {
                        fetchData();
                    } else if (activeNav.value === 'monitor') {
                        fetchDeviceOverview();
                    } else if (activeNav.value === 'traffic_analysis') {
                        fetchInterfaceAnalytics();
                    } else if (activeNav.value === 'network') {
                        fetchConfigs();
                        fetchSubnetsSummary();
                        if (selectedExporterIp.value) loadDeviceInterfaces(selectedExporterIp.value);
                    } else if (activeNav.value === 'settings') {
                        fetchConfigs();
                    }
                }"""

script_content = script_content.replace(old_states_decl, new_states_decl)

old_open_iface = """                function openInterfaceDetail(dev, ifc) {
                    currentSelectedDevice.value = dev;
                    currentSelectedInterface.value = ifc;
                    deviceViewMode.value = 'interface_detail';"""

new_open_iface = """                function openInterfaceDetail(dev, ifc) {
                    selectedAnalysisDeviceIp.value = dev.exporter_ip;
                    selectedAnalysisIfIndex.value = ifc.if_index;
                    currentSelectedDevice.value = dev;
                    currentSelectedInterface.value = ifc;
                    activeNav.value = 'traffic_analysis';"""

script_content = script_content.replace(old_open_iface, new_open_iface)

old_on_mounted = """                    // Initial load: Fetch device monitoring overview as primary view
                    fetchDeviceOverview();"""

new_on_mounted = """                    // Initial load: Fetch macro dashboard, device monitoring, config & subnets summary
                    fetchData();
                    fetchDeviceOverview();
                    fetchConfigs();
                    fetchSubnetsSummary();"""

script_content = script_content.replace(old_on_mounted, new_on_mounted)

# Update saveBusinessGroup to re-fetch subnets summary
script_content = script_content.replace(
    "const bgRes = await fetch(`${apiBase}/config/business-groups`).then(r => r.json());\n                            if (bgRes.code === 0) businessGroups.value = bgRes.data || [];",
    "const bgRes = await fetch(`${apiBase}/config/business-groups`).then(r => r.json());\n                            if (bgRes.code === 0) businessGroups.value = bgRes.data || [];\n                            fetchSubnetsSummary();"
)

old_return = """                    activeMainView,
                    deviceViewMode,"""

new_return = """                    activeNav,
                    networkSubTab,
                    settingsSubTab,
                    subnetsSummaryList,
                    subnetsLoading,
                    totalSubnetActiveIPs,
                    totalSubnetBytesFormatted,
                    topSubnetName,
                    topSubnetPct,
                    resolveSubnetForIP,
                    editingDevice,
                    isNewDevice,
                    openNewDeviceModal,
                    editDeviceAttributes,
                    saveDeviceCustomAttributes,
                    getDeviceTypeBadgeClass,
                    fetchSubnetsSummary,
                    selectedAnalysisDeviceIp,
                    selectedAnalysisIfIndex,
                    currentAnalysisDeviceInterfaces,
                    onAnalysisDeviceChange,
                    onAnalysisInterfaceChange,
                    switchNav,
                    refreshCurrentNav,"""

script_content = script_content.replace(old_return, new_return)

clean_head = "".join(head_lines)
if clean_head.rstrip().endswith("<body>"):
    clean_head = clean_head.rstrip()[:-6]

final_html = clean_head + "\n" + html_body + "\n" + script_content

with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write(final_html)

print(f"Generated {OUT_FILE}, total lines: {final_html.count(chr(10)) + 1}, bytes: {len(final_html)}")
