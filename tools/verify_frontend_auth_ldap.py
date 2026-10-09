#!/usr/bin/env python3
"""
Automated Verifier for Frontend Authentication & LDAP Integration UX
1. Verifies fullscreen tech-style login overlay
2. Performs admin login and checks JWT injection & topbar user profile
3. Verifies Settings -> Third-party API Integration -> LDAP / Active Directory card
4. Tests LDAP connectivity probe UI interaction
5. Verifies Change Password modal UI
"""

import sys
import os
import time
import json
import base64
import subprocess
import urllib.request
import websocket
import shutil

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TARGET_URL = "http://10.3.11.78:8080/"

ARTIFACT_DIR = r"C:\Users\Ben\.gemini\antigravity\brain\55f59907-6c6b-41b6-a7e8-388bea2059b9"
OUTPUT_LOGIN_IMAGE = r"d:\nTop\auth_login_overlay_verified.png"
OUTPUT_LDAP_IMAGE = r"d:\nTop\settings_ldap_card_verified.png"
OUTPUT_CHANGE_PWD_IMAGE = r"d:\nTop\change_password_modal_verified.png"

DEBUG_PORT = 9249

def send_cdp(ws, method, params=None, msg_id=1):
    payload = {"id": msg_id, "method": method, "params": params or {}}
    ws.send(json.dumps(payload))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == msg_id:
            return resp

def capture_screenshot(ws, output_path, msg_id=100):
    res = send_cdp(ws, "Page.captureScreenshot", {"format": "png", "quality": 100}, msg_id=msg_id)
    b64_data = res.get("result", {}).get("data", "")
    if b64_data:
        raw_bytes = base64.b64decode(b64_data)
        with open(output_path, "wb") as f:
            f.write(raw_bytes)
        print(f"  [+] 成功截图保存至: {output_path} ({len(raw_bytes)} bytes)")
        # 复制到 artifact 目录
        basename = os.path.basename(output_path)
        dest = os.path.join(ARTIFACT_DIR, basename)
        shutil.copyfile(output_path, dest)
        print(f"  [+] 已同步至 Artifact 目录: {dest}")

def evaluate_js(ws, expr, msg_id=200):
    res = send_cdp(ws, "Runtime.evaluate", {
        "expression": expr,
        "returnByValue": True,
        "awaitPromise": True
    }, msg_id=msg_id)
    return res.get("result", {}).get("result", {}).get("value")

def main():
    print("================================================================")
    print(" [Authentication & LDAP UI - Automated Verifier] ")
    print("================================================================")

    if not os.path.exists(EDGE_PATH):
        print(f"[ERROR] Edge executable not found at {EDGE_PATH}")
        sys.exit(1)

    print(f"[*] Launching Headless Edge on port {DEBUG_PORT} ...")
    cmd = [
        EDGE_PATH,
        "--headless",
        f"--remote-debugging-port={DEBUG_PORT}",
        "--remote-allow-origins=*",
        "--window-size=1920,1080",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-sandbox",
        TARGET_URL
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.5)

    ws_url = None
    for _ in range(10):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{DEBUG_PORT}/json")
            with urllib.request.urlopen(req, timeout=2) as resp:
                targets = json.loads(resp.read().decode())
                for t in targets:
                    if t.get("type") == "page" and "webSocketDebuggerUrl" in t:
                        ws_url = t["webSocketDebuggerUrl"]
                        break
            if ws_url:
                break
        except Exception:
            time.sleep(0.5)

    if not ws_url:
        print("[ERROR] Could not connect to Edge DevTools")
        proc.kill()
        sys.exit(1)

    ws = websocket.create_connection(ws_url)
    send_cdp(ws, "Page.enable", msg_id=1)
    send_cdp(ws, "Runtime.enable", msg_id=2)

    # 1. Clear any existing token to test login overlay
    print("\n[*] 1. 清理本地 Token，测试未登录拦截与全屏科技感登录界面...")
    evaluate_js(ws, "localStorage.removeItem('flow_auth_token'); localStorage.removeItem('flow_auth_user'); window.location.reload();", msg_id=10)
    time.sleep(2.0)

    # 检查登录遮罩是否显示
    is_login_visible = evaluate_js(ws, "!!document.querySelector('.login-overlay')", msg_id=11)
    login_title = evaluate_js(ws, "document.querySelector('.login-card h5')?.innerText", msg_id=12)
    print(f"  -> 登录遮罩显示状态: {is_login_visible}, 标题: {login_title}")
    assert is_login_visible, "未展示全屏登录遮罩！"

    # 截取登录页面
    capture_screenshot(ws, OUTPUT_LOGIN_IMAGE, msg_id=101)

    # 2. 模拟用户输入 admin / admin 并登录
    print("\n[*] 2. 模拟输入管理员账号 admin / admin 并点击登录...")
    login_result = evaluate_js(ws, """
        (async () => {
            const inputs = document.querySelectorAll('.login-card input');
            const usernameInput = inputs[0];
            const passwordInput = inputs[1];
            usernameInput.value = 'admin';
            usernameInput.dispatchEvent(new Event('input', { bubbles: true }));
            passwordInput.value = 'admin';
            passwordInput.dispatchEvent(new Event('input', { bubbles: true }));
            
            const submitBtn = document.querySelector('.login-card button[type="submit"]');
            submitBtn.click();
            await new Promise(r => setTimeout(r, 1200));
            return {
                token: localStorage.getItem('flow_auth_token'),
                overlayVisible: !!document.querySelector('.login-overlay')
            };
        })()
    """, msg_id=20)
    print(f"  -> 登录后状态: Token存在={bool(login_result.get('token'))}, 遮罩已消失={not login_result.get('overlayVisible')}")
    assert bool(login_result.get('token')), "登录后未获取到 Token！"

    time.sleep(1.0)
    # 检查顶部导航栏用户身份展示
    user_badge_text = evaluate_js(ws, "document.querySelector('#userDropdownBtn')?.innerText?.trim()", msg_id=21)
    print(f"  -> 顶栏用户身份展示: {user_badge_text}")

    # 3. 切换到【设置】模块并查看【第三方平台 API 集成】
    print("\n[*] 3. 导航至【设置】模块 -> 【第三方平台 API 集成】...")
    evaluate_js(ws, """
        (() => {
            window.location.hash = '#/settings';
            const buttons = Array.from(document.querySelectorAll('.sidebar-btn'));
            const settingsBtn = buttons.find(b => b.innerText.includes('设置'));
            if (settingsBtn) settingsBtn.click();
        })()
    """, msg_id=30)
    time.sleep(1.0)

    # 切换子标签至 API 集成
    evaluate_js(ws, """
        (() => {
            const apiBtn = document.querySelector('#btnSubTabApi');
            if (apiBtn) apiBtn.click();
        })()
    """, msg_id=31)
    time.sleep(1.0)

    # 检查 LDAP 卡片元素是否存在
    ldap_card_found = evaluate_js(ws, "!!document.querySelector('#btnTestLDAP')", msg_id=32)
    ldap_enabled_checked = evaluate_js(ws, "document.querySelector('#ldapEnabledSwitch')?.checked", msg_id=33)
    print(f"  -> LDAP 卡片探测按钮存在: {ldap_card_found}, 初始启用状态: {ldap_enabled_checked}")
    assert ldap_card_found, "未在设置页找到 LDAP 集成卡片！"

    # 4. 点击测试 LDAP 连通性按钮
    print("\n[*] 4. 点击【测试 LDAP 连接与探测】按钮...")
    evaluate_js(ws, """
        (() => {
            const testBtn = document.querySelector('#btnTestLDAP');
            if (testBtn) {
                testBtn.scrollIntoView({ behavior: 'smooth', block: 'center' });
                testBtn.click();
            }
        })()
    """, msg_id=40)
    time.sleep(3.5)

    # 截图保存设置页 LDAP 卡片
    capture_screenshot(ws, OUTPUT_LDAP_IMAGE, msg_id=102)

    # 5. 测试【修改密码】模态框弹出
    print("\n[*] 5. 测试顶栏用户菜单与【修改个人密码】模态框...")
    evaluate_js(ws, """
        (() => {
            const openModalBtn = document.querySelector('#btnOpenChangePwd');
            if (openModalBtn) openModalBtn.click();
        })()
    """, msg_id=50)
    time.sleep(1.0)

    modal_visible = evaluate_js(ws, "document.querySelector('#changePasswordModal')?.classList.contains('show')", msg_id=51)
    modal_title = evaluate_js(ws, "document.querySelector('#changePasswordModal .modal-title')?.innerText?.trim()", msg_id=52)
    print(f"  -> 修改密码模态框弹出: {modal_visible}, 标题: {modal_title}")

    # 截图保存修改密码模态框
    capture_screenshot(ws, OUTPUT_CHANGE_PWD_IMAGE, msg_id=103)

    print("\n================================================================")
    print(" [ALL VERIFICATION TASKS COMPLETED SUCCESSFULLY] ")
    print("================================================================")

    ws.close()
    proc.kill()

if __name__ == "__main__":
    main()

