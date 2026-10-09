with open(r"d:\nTop\frontend\index.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

depth = 0
for idx in range(303, len(lines)):
    line = lines[idx]
    open_count = line.count("<div")
    close_count = line.count("</div>")
    depth += (open_count - close_count)
    if "activeNav === 'dashboard'" in line:
        print(f"Line {idx+1}: activeNav === 'dashboard', depth = {depth}")
    if "activeNav === 'monitor'" in line:
        print(f"Line {idx+1}: activeNav === 'monitor', depth = {depth}")
    if "activeNav === 'traffic_analysis'" in line:
        print(f"Line {idx+1}: activeNav === 'traffic_analysis', depth = {depth}")
    if "activeNav === 'network'" in line:
        print(f"Line {idx+1}: activeNav === 'network', depth = {depth}")
    if "activeNav === 'settings'" in line:
        print(f"Line {idx+1}: activeNav === 'settings', depth = {depth}")
    if "</main>" in line:
        print(f"Line {idx+1}: </main>, depth = {depth}")
    if depth <= 0:
        print(f"Line {idx+1} reached depth <= 0: {depth} | {line.strip()[:80]}")
        break
