import subprocess

def query(q):
    cmd = [
        "ssh", "-i", "C:/Users/Ben/.ssh/id_ed25519", "ben@10.3.11.78",
        f"clickhouse-client --query \"{q}\""
    ]
    return subprocess.check_output(cmd).decode()

print("=== SHOW CREATE TABLE ntopng.flows ===")
print(query("SHOW CREATE TABLE ntopng.flows"))
print("\n=== SHOW CREATE TABLE ntopng.exporter_devices ===")
print(query("SHOW CREATE TABLE ntopng.exporter_devices"))
