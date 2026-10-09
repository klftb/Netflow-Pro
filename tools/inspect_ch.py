import subprocess

cmd = [
    "ssh", "-i", "C:/Users/Ben/.ssh/id_ed25519", "ben@10.3.11.78",
    "clickhouse-client --query \"SELECT table, sum(rows), formatReadableSize(sum(data_compressed_bytes)), formatReadableSize(sum(data_uncompressed_bytes)) FROM system.parts WHERE database='ntopng' AND active GROUP BY table ORDER BY sum(rows) DESC\""
]
out = subprocess.check_output(cmd).decode()
print("Table\tRows\tCompressed\tUncompressed")
print(out)
