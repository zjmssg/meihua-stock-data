#!/usr/bin/env python3
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'data/manifest.json').read_text(encoding='utf-8'))
errors=[]
for date in manifest.get('available_dates',[]):
 p=ROOT/'data/daily'/f'{date}.json'
 if not p.exists(): errors.append(f'{date}: 文件不存在'); continue
 d=json.loads(p.read_text(encoding='utf-8'))
 rows=d.get('rows',[]); cols=d.get('columns',[])
 if len(rows)<1000: errors.append(f'{date}: 仅{len(rows)}行')
 if 'code' not in cols or 'close' not in cols: errors.append(f'{date}: 字段缺失')
if errors:
 print('\n'.join(errors)); sys.exit(1)
print(f"验证通过：{len(manifest.get('available_dates',[]))}个交易日，最新{manifest.get('latest')}")
