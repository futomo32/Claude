# -*- coding: utf-8 -*-
"""data/real/csv/ の CSV 114ファイルが「何のテーブルか」を一覧にする診断ツール。

- 表示するのは【ファイル名・行数・列数】だけ。セルの中身(個人情報)は一切表示しない。
- 目的: 11xlsxで足りるか / CSVから追加で取り込むべきマスタ表(担当者・分類・
  コード対応表など)があるかを、中身を見ずに判断する。

使い方:
  python3 scripts/diag_real_csv.py            # data/real/csv を見る
  python3 scripts/diag_real_csv.py <フォルダ>  # 任意フォルダを指定

出力: 画面 + data/real/csv一覧.txt (gitignore下・GitHubには載らない)
"""
import csv
import glob
import io
import os
import sys

target = "data/real/csv"
if len(sys.argv) > 1:
    target = sys.argv[1]
elif not os.path.isdir(target):
    # フォールバック: data/real 直下のcsv
    if glob.glob(os.path.join("data/real", "*.csv")):
        target = "data/real"

files = sorted(glob.glob(os.path.join(target, "*.csv")))
if not files:
    print(f"[エラー] {target} に csv がありません。")
    print("  CSV 114ファイルを data/real/csv/ に入れてから実行してください。")
    sys.exit(1)


def read_text(path):
    """Shift-JIS(cp932)優先で開く。ダメならUTF-8。宝飾ナビは概ねcp932。"""
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                return f.read(), enc
        except UnicodeDecodeError:
            continue
    # 最後の手段: 文字化けは許容して開く
    with open(path, "r", encoding="cp932", errors="replace", newline="") as f:
        return f.read(), "cp932(一部化け)"


out = []
w = out.append
w(f"CSV一覧 (対象: {target} / {len(files)}ファイル)")
w("※ 表示はファイル名・行数(データ件数)・列数のみ。中身は出しません。")
w("")
w(f"{'ファイル名':40}  {'データ件数':>10}  {'列数':>5}  文字コード")
w("-" * 78)

rows_summary = []
for fn in files:
    text, enc = read_text(fn)
    reader = csv.reader(io.StringIO(text))
    n_rows = 0
    n_cols = 0
    for i, row in enumerate(reader):
        if i == 0:
            n_cols = len(row)
        if any(c.strip() for c in row):
            n_rows += 1
    # 見出し行がある想定なら「データ件数 = 総行数 - 1」だが、
    # 生ダンプは見出し無しのこともあるので総行数(非空)をそのまま出す
    base = os.path.basename(fn)
    rows_summary.append((base, n_rows, n_cols))
    w(f"{base:40}  {n_rows:>10,}  {n_cols:>5}  {enc}")

w("")
w("=== 件数が多い順(データ本体らしいテーブル) TOP20 ===")
for base, n_rows, n_cols in sorted(rows_summary, key=lambda x: -x[1])[:20]:
    w(f"  {base:40}  {n_rows:>10,}行  {n_cols}列")

w("")
w("=== 件数が少ない表(マスタ・コード対応表の候補) ===")
for base, n_rows, n_cols in sorted(rows_summary, key=lambda x: x[1]):
    if n_rows <= 200:
        w(f"  {base:40}  {n_rows:>6,}行  {n_cols}列")

report = os.path.join(target, "csv一覧.txt")
with open(report, "w", encoding="utf-8") as f:
    f.write("\n".join(out))

for line in out:
    print(line)
print()
print(f"(一覧を {report} にも保存しました)")
