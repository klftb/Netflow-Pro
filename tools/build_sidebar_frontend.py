#!/usr/bin/env python3
"""
Build modernized sidebar-based frontend for NetFlow Analyzer Pro.
100% Balanced DOM tree, flat parallel navigation:
- 仪表盘 (dashboard)
- 监控 (monitor)
- 流量分析 (traffic_analysis)
- 网络 (network)
- 设置 (settings)
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

# Replace breadcrumb header with selector toolbar
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

# 5. Extract Network (1-indexed lines 1014..1190) -> 0-indexed [1013:1190]
network_block = "".join(lines[1013:1190])
network_block = network_block.replace(
    '<div class="tab-pane fade" id="tab-exporters" role="tabpanel">',
    '<div v-show="activeNav === \'network\'">'
)

# 6. Extract Settings Tabs:
# Tab 1: Groups (1-indexed lines 915..961) -> 0-indexed [914:961]
groups_block = "".join(lines[914:961])
groups_block = groups_block.replace(
    '<div class="tab-pane fade show active" id="tab-groups" role="tabpanel">',
    '<div v-show="settingsSubTab === \'groups\'">'
)

# Tab 2: Apps (1-indexed lines 964..1011) -> 0-indexed [963:1011]
apps_block = "".join(lines[963:1011])
apps_block = apps_block.replace(
    '<div class="tab-pane fade" id="tab-apps" role="tabpanel">',
    '<div v-show="settingsSubTab === \'apps\'">'
)

# Tab 4: System (1-indexed lines 1193..1237) -> 0-indexed [1192:1237]
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
                                <button type="button" class="btn btn-sm" :class="settingsSubTab === 'groups' ? 'btn-primary' : 'btn-outline-secondary'" @click="settingsSubTab = 'groups'">
                                    <i class="fas fa-building me-1"></i>业务组与 CIDR 网段
                                </button>
                            </li>
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

                    {groups_block}
                    {apps_block}
                    {system_block}
                </div>"""

# 7. Layout HTML Body
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
                        <span v-else-if="activeNav === 'network'"><i class="fas fa-network-wired text-primary me-1"></i>网络设备与 SNMP 探测管理</span>
                        <span v-else-if="activeNav === 'settings'"><i class="fas fa-sliders-h text-primary me-1"></i>系统配置与基础规则管理</span>
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

                <!-- ==================== 4. 网络 (Network) ==================== -->
                {network_block}

                {settings_block}
            </div>
        </main>
    </div>
"""

# 8. Extract Script area (from line 1248 which is <script>)
script_lines = lines[1248:]
script_content = "".join(script_lines)

# Vue updates
script_content = script_content.replace(
    "const { createApp, ref, onMounted, nextTick } = Vue;",
    "const { createApp, ref, computed, onMounted, nextTick } = Vue;"
)

old_states_decl = "const activeMainView = ref('devices'); // 'devices' (Default) or 'global'\n                const deviceViewMode = ref('list'); // 'list' or 'interface_detail'"
new_states_decl = """const activeNav = ref('dashboard'); // 'dashboard', 'monitor', 'traffic_analysis', 'network', 'settings'
                const settingsSubTab = ref('groups'); // 'groups', 'apps', 'system'
                const selectedAnalysisDeviceIp = ref('');
                const selectedAnalysisIfIndex = ref(null);

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
                            loadConfig();
                            if (exporterList.value.length > 0 && !selectedExporterIp.value) {
                                selectDeviceForInterface(exporterList.value[0].exporter_ip);
                            }
                        } else if (nav === 'settings') {
                            loadConfig();
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
                        loadConfig();
                        if (selectedExporterIp.value) loadDeviceInterfaces(selectedExporterIp.value);
                    } else if (activeNav.value === 'settings') {
                        loadConfig();
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

old_on_mounted = """                onMounted(() => {
                    fetchDeviceOverview();
                    fetchData();
                    loadConfig();"""

new_on_mounted = """                onMounted(() => {
                    fetchData(); // 默认首屏是仪表盘
                    fetchDeviceOverview(); // 预热设备监控数据
                    loadConfig();"""

script_content = script_content.replace(old_on_mounted, new_on_mounted)

old_return = """                    activeMainView,
                    deviceViewMode,"""

new_return = """                    activeNav,
                    settingsSubTab,
                    selectedAnalysisDeviceIp,
                    selectedAnalysisIfIndex,
                    currentAnalysisDeviceInterfaces,
                    onAnalysisDeviceChange,
                    onAnalysisInterfaceChange,
                    switchNav,
                    refreshCurrentNav,"""

script_content = script_content.replace(old_return, new_return)

# Combine entire final HTML
clean_head = "".join(head_lines)
if clean_head.rstrip().endswith("<body>"):
    clean_head = clean_head.rstrip()[:-6]

final_html = clean_head + "\n" + html_body + "\n" + script_content

with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write(final_html)

print(f"Generated {OUT_FILE}, total lines: {final_html.count(chr(10)) + 1}, bytes: {len(final_html)}")
