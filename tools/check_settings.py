import re

with open(r"d:\nTop\frontend\index.html", "r", encoding="utf-8") as f:
    text = f.read()

matches = [m.start() for m in re.finditer(r"activeNav === 'settings'", text)]
print("Matches:", matches)
for m in matches:
    print("=" * 40)
    print(text[m-20:m+500])
