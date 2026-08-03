# -*- coding: utf-8 -*-
"""実データ(data/real/)の中から「この値がどの表のどの列に入っているか」を逆引きする。

作った理由(2026-08-03):
  値札タグの裏に刷られている「UA-3602」のような固有の品番が、宝飾ナビのどの列に
  入っているのか分からなかった。トキワの取込は宝飾ナビの117列のうち一部しか使って
  いないので、tokiwa.db を探しても見つからない。元のCSV/xlsxを見る必要がある。
  移行で取り込む列を決めるための調査に使う。

使い方:
  python3 scripts/find_column.py 20368              # 商品番号20368の行の中身を全部出す
  python3 scripts/find_column.py 20368 UA-3602      # さらに UA-3602 が入っている列に★を付ける
  python3 scripts/find_column.py 20368 UA-3602 --contains   # キーを部分一致で探す

出力するもの:
  ファイル名 / シート名 / 列名 / その行の値 だけ。
  ★個人情報らしい列(氏名・カナ・住所・電話・生年月日・メール等)は値を伏せ字にする。
  ★一致した行だけを出す(他の行は一切出さない)。
  この方針は CLAUDE.md「診断・分析スクリプトは個人情報を画面出力しない」に合わせている。

照合のしかた:
  全角/半角・大文字小文字の違いを吸収して比べる(NFKC正規化＋casefold)。
  タグの実物は文字が切れていることがあるので、探したい値は部分一致で判定する。
"""
import glob
import os
import re
import sys
import unicodedata

REAL_DIR = "data/real"
MAX_ROWS_PER_FILE = 5      # 1ファイルから出す行数の上限(取り違えて大量に出さないため)
MAX_VALUE_LEN = 80         # 1つの値の表示上限

# 伏せ字のルールは scripts/_privacy.py にまとめてある(直す時はそちらだけ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _privacy import mask as mask_value   # noqa: E402


def norm(v):
    """全角/半角・大文字小文字の違いを吸収した比較用の文字列にする。"""
    if v is None:
        return ""
    s = unicodedata.normalize("NFKC", str(v)).strip()
    return s.casefold()


def show(col, val):
    """列名と値を1行にする。個人情報らしい列・値は伏せる(判定は _privacy.py)。"""
    shown = mask_value(col, val, MAX_VALUE_LEN)
    return None if shown is None else f"    {col} = {shown}"


def read_csv_rows(path):
    """CSVを (見出し, 行) で返す。宝飾ナビの書き出しは cp932 のことが多いので順に試す。"""
    import csv
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                rows = list(csv.reader(f))
            break
        except UnicodeDecodeError:
            continue
    else:
        print(f"  [読めません] 文字コードを判定できませんでした: {path}")
        return None, []
    if not rows:
        return [], []
    return rows[0], rows[1:]


def read_xlsx_sheets(path):
    """xlsx を [(シート名, 見出し, 行の反復子)] で返す。"""
    try:
        import openpyxl
    except ImportError:
        print("  [読めません] xlsx を読むには openpyxl が必要です → pip3 install openpyxl")
        return []
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [読めません] {os.path.basename(path)}: {e}")
        return []
    out = []
    for ws in wb.worksheets:
        it = ws.iter_rows(values_only=True)
        try:
            head = next(it)
        except StopIteration:
            continue
        out.append((ws.title, list(head), it))
    return out


def scan_rows(head, rows, key, wanted, contains, where, hits):
    """1つの表を走査して、キーに一致した行の中身を出す。"""
    nkey = norm(key)
    nwanted = [norm(w) for w in wanted]
    shown = 0
    for i, row in enumerate(rows, start=2):     # 2行目からがデータ(1行目=見出し)
        cells = [norm(c) for c in row]
        found = any(c == nkey for c in cells) if not contains else any(nkey and nkey in c for c in cells)
        if not found:
            continue
        shown += 1
        if shown > MAX_ROWS_PER_FILE:
            print(f"  … 同じキーの行が他にもあります(表示は{MAX_ROWS_PER_FILE}行まで)")
            break
        print(f"\n  ■ {where} の {i}行目 が一致")
        for col, val in zip(head or [], row):
            line = show(col, val)
            if not line:
                continue
            nv = norm(val)
            star = any(w and w in nv for w in nwanted)
            if star:
                hits.append((where, col, str(val).strip()))
            print(("  ★" + line[4:]) if star else line)
    return shown


def main():
    args = [a for a in sys.argv[1:] if a != "--contains"]
    contains = "--contains" in sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    key, wanted = args[0], args[1:]

    if not os.path.isdir(REAL_DIR):
        print(f"[エラー] {REAL_DIR} がありません。実データのあるPCで実行してください。")
        sys.exit(1)

    files = sorted(
        glob.glob(os.path.join(REAL_DIR, "**", "*.csv"), recursive=True) +
        glob.glob(os.path.join(REAL_DIR, "**", "*.xlsx"), recursive=True))
    files = [f for f in files if not os.path.basename(f).startswith("~$")]  # Excelの一時ファイルは除く
    if not files:
        print(f"[エラー] {REAL_DIR} に csv / xlsx がありません。")
        sys.exit(1)

    print("=" * 60)
    print(f"  探すキー : {key}" + ("  (部分一致)" if contains else "  (完全一致)"))
    if wanted:
        print(f"  ★を付ける値: {', '.join(wanted)}")
    print(f"  対象ファイル: {len(files)} 件")
    print("  ※個人情報らしい列の値は伏せ字にします")
    print("=" * 60)

    total, hits = 0, []
    for path in files:
        rel = os.path.relpath(path)
        if path.lower().endswith(".csv"):
            head, rows = read_csv_rows(path)
            if head is None:
                continue
            total += scan_rows(head, rows, key, wanted, contains, rel, hits)
        else:
            for sheet, head, it in read_xlsx_sheets(path):
                total += scan_rows(head, it, key, wanted, contains, f"{rel} [{sheet}]", hits)

    print("\n" + "=" * 60)
    if total == 0:
        print(f"  「{key}」に一致する行は見つかりませんでした。")
        if not contains:
            print("  → --contains を付けて部分一致でもう一度試してください:")
            print(f"     python3 scripts/find_column.py {' '.join(sys.argv[1:])} --contains")
    else:
        print(f"  一致した行: {total} 件")
        if wanted:
            if hits:
                print(f"\n  ★探していた値が入っていた列は次のとおりです:")
                for where, col, val in hits:
                    print(f"     {where}  列名「{col}」  値: {val}")
                print("\n  → この列名を伝えてもらえれば、トキワへの取り込みと入力欄を用意します。")
            else:
                print(f"\n  探していた値({', '.join(wanted)})はどの列にも見つかりませんでした。")
                print("  → 上に出ている列の一覧から、それらしい列名を探してみてください。")
                print("     (実札の文字が切れている場合は、値の一部だけで指定し直すのも有効です)")
    print("=" * 60)


if __name__ == "__main__":
    main()
