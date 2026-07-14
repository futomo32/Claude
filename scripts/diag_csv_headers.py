# -*- coding: utf-8 -*-
"""data/real/csv/ の全CSVの「列見出し(1行目)だけ」を1ファイルに書き出す。

- 出力するのは各テーブルの【列名のみ】。データ行(顧客名・電話など)は一切出さない。
- これを共有してもらえれば、フルCSV移行のためのDB設計と取込プログラムを組める。

安全確認: 1行目が「列名」ではなく実データに見える表があれば教えてください
(その表だけ扱いを変えます)。件数の突き合わせ上、1行目は見出しの想定です。

使い方:
  python3 scripts/diag_csv_headers.py            # data/real/csv を見る
  python3 scripts/diag_csv_headers.py <フォルダ>
出力: data/real/csv/全ヘッダ一覧.txt
"""
import csv
import glob
import io
import os
import sys

target = "data/real/csv"
if len(sys.argv) > 1:
    target = sys.argv[1]
elif not os.path.isdir(target) and glob.glob(os.path.join("data/real", "*.csv")):
    target = "data/real"

files = sorted(glob.glob(os.path.join(target, "*.csv")))
if not files:
    print(f"[エラー] {target} に csv がありません。")
    sys.exit(1)


def read_first_line(path):
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                first = f.readline()
            return first, enc
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="cp932", errors="replace", newline="") as f:
        return f.readline(), "cp932(一部化け)"


out = []
w = out.append
w("# 宝飾ナビ 全CSV 列見出し一覧(列名のみ・データは含みません)")
w(f"# 対象: {target} / {len(files)}ファイル")
w("")
for fn in files:
    first, enc = read_first_line(fn)
    # csvパースで列に分解(引用符やカンマ入りに対応)
    cols = next(csv.reader(io.StringIO(first)), [])
    base = os.path.basename(fn)
    w(f"## {base}  ({len(cols)}列)")
    w("   " + " | ".join(f"{i}:{c}" for i, c in enumerate(cols)))
    w("")

report = os.path.join(target, "全ヘッダ一覧.txt")
with open(report, "w", encoding="utf-8") as f:
    f.write("\n".join(out))

print(f"書き出しました: {report}")
print(f"({len(files)}テーブル分の列見出し)")
print("この 全ヘッダ一覧.txt をアップロードして共有してください(列名のみ・個人情報なし)。")
