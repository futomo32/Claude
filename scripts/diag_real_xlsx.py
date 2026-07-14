# -*- coding: utf-8 -*-
"""data/real/ の xlsx の「構造」だけを調べる診断ツール(個人情報は表示しない)。

各ファイルのシート名・行数・列数と、1行目(見出し候補)のセル数だけを表示する。
なぜ analyze_real_data.py が「0件」になるのかを切り分けるためのツール。

使い方:
  python3 scripts/diag_real_xlsx.py
"""
import glob
import os
import sys

try:
    import openpyxl
except ImportError:
    print("[エラー] openpyxl が必要です。 pip3 install openpyxl を実行してください。")
    sys.exit(1)

target = "data/real"
files = sorted(glob.glob(os.path.join(target, "*.xlsx")))
if not files:
    print(f"[エラー] {target} に xlsx がありません。")
    sys.exit(1)

for fn in files:
    print(f"■ {os.path.basename(fn)}")
    wb = openpyxl.load_workbook(fn, read_only=True, data_only=True)
    print(f"  シート数: {len(wb.sheetnames)}  シート名: {wb.sheetnames}")
    print(f"  アクティブシート(既定で読む対象): {wb.active.title}")
    for name in wb.sheetnames:
        ws = wb[name]
        # 先頭10行だけ見て、非空セルの多い行(見出し候補)を探す
        best_row_idx = None
        best_count = 0
        preview_rows = 0
        for i, row in enumerate(ws.iter_rows(values_only=True, max_row=10), start=1):
            preview_rows += 1
            non_empty = sum(1 for c in row if c is not None and str(c).strip() != "")
            if non_empty > best_count:
                best_count = non_empty
                best_row_idx = i
        print(f"    - シート「{name}」: 最大行={ws.max_row} 最大列={ws.max_column} "
              f"/ 先頭10行中もっとも列が埋まっている行= {best_row_idx}行目(非空{best_count}列)")
    wb.close()
    print()

print("見るポイント:")
print("- 実データが入っていそうな行数・列数のシートが「アクティブシート」と一致しているか")
print("- 一致していない場合、そのシート名を教えてください(analyze/importの読み込み先を修正します)")
