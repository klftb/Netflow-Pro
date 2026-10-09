with open(r'd:\nTop\frontend\index.html.bak', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("Lines in modal (878 to 1248):")
for i in range(877, 1248):
    l = lines[i]
    if 'tab-pane' in l or 'Tab ' in l or 'role="tab"' in l:
        print(f"{i+1}: {l.strip()}")
