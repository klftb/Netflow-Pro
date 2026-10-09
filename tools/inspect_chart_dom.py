with open(r'd:\nTop\frontend\index.html', encoding='utf-8') as f:
    for idx, line in enumerate(f, 1):
        if 'trendChart' in line or 'sankeyChart' in line:
            print(f'{idx}: {line.strip()[:120]}')
