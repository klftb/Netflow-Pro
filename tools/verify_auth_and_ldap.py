import requests
import json
import sys

BASE_URL = "http://10.3.11.78:8080/api/v1"

def test_auth_workflow():
    print("[1] 测试未提供 Token 访问受保护接口...")
    r = requests.get(f"{BASE_URL}/config/business-groups")
    assert r.status_code == 401, f"期望 401，实际收到 {r.status_code}: {r.text}"
    print("  -> 成功被拦截，返回 401:", r.json())

    print("\n[2] 测试错误密码登录...")
    r = requests.post(f"{BASE_URL}/auth/login", json={"username": "admin", "password": "wrong_password_test"})
    assert r.status_code == 401, f"期望 401，实际收到 {r.status_code}"
    print("  -> 成功拦截错误密码:", r.json())

    print("\n[3] 测试初始管理员登录 (admin / admin)...")
    r = requests.post(f"{BASE_URL}/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, f"期望 200，实际收到 {r.status_code}: {r.text}"
    login_data = r.json()
    assert login_data.get("code") == 0, f"登录业务码错误: {login_data}"
    token = login_data["data"]["token"]
    user = login_data["data"]["user"]
    print(f"  -> 登录成功! 获得 Token: {token[:20]}... 用户: {user['username']} 角色: {user['role']}")

    print("\n[4] 测试携带 Token 访问受保护接口...")
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{BASE_URL}/config/business-groups", headers=headers)
    assert r.status_code == 200, f"期望 200，实际收到 {r.status_code}: {r.text}"
    print(f"  -> 授权访问成功! 获取到 {len(r.json().get('data', []))} 个业务网段")

    print("\n[5] 测试获取当前用户信息 (/auth/me)...")
    r = requests.get(f"{BASE_URL}/auth/me", headers=headers)
    assert r.status_code == 200, f"期望 200，实际收到 {r.status_code}: {r.text}"
    me = r.json().get("data")
    assert me["username"] == "admin", f"用户不匹配: {me}"
    print("  -> 获取成功:", me)

    print("\n[6] 测试 LDAP 连通性测试接口 (/config/ldap/test)...")
    ldap_test_payload = {
        "url": "ldap://10.3.1.20:389",
        "base_dn": "dc=example,dc=com",
        "bind_dn": "",
        "bind_password": ""
    }
    r = requests.post(f"{BASE_URL}/config/ldap/test", json=ldap_test_payload, headers=headers)
    print("  -> LDAP 探测返回状态:", r.status_code, r.json())

    print("\n[7] 测试本地管理员修改密码流程...")
    # 修改为新密码
    r = requests.post(f"{BASE_URL}/auth/change-password", json={
        "old_password": "admin",
        "new_password": "admin_test"
    }, headers=headers)
    assert r.status_code == 200 and r.json().get("code") == 0, f"修改密码失败: {r.text}"
    print("  -> 密码成功更新为新密码")

    # 使用新密码登录验证
    r = requests.post(f"{BASE_URL}/auth/login", json={"username": "admin", "password": "admin_test"})
    assert r.status_code == 200 and r.json().get("code") == 0, "新密码登录失败"
    new_token = r.json()["data"]["token"]
    print("  -> 使用新密码登录成功！")

    # 将密码恢复为 admin 保持系统开箱默认一致
    r = requests.post(f"{BASE_URL}/auth/change-password", json={
        "old_password": "admin_test",
        "new_password": "admin"
    }, headers={"Authorization": f"Bearer {new_token}"})
    assert r.status_code == 200 and r.json().get("code") == 0, "密码复原失败"
    print("  -> 密码已成功复原为开箱默认值 admin")

    print("\n=== 所有认证与后端验证全部通过 (100% SUCCESS) ===")

if __name__ == "__main__":
    test_auth_workflow()

