#!/usr/bin/env python3
"""仕入先マスタに「仕入先コード」を埋める(再取込は不要)。

  python3 scripts/fill_supplier_codes.py            # 下読み(何も書き換えない)
  python3 scripts/fill_supplier_codes.py --apply    # 実際に書き込む

★なぜ必要か
  取込(import_csv.py)は m_siiresaki を「コード→名前」の変換表としてしか使っておらず、
  **コードそのものを保存していなかった**。そのため既存のDBには仕入先コードが無い。
  ここで名前を突き合わせて後から埋める。売上・在庫・顧客には一切触らない。

★安全のための決まり
  ・既定は下読み。--apply を付けた時だけ書き込む。
  ・**既にコードが入っている仕入先は上書きしない**(手で直した値を消さないため)。
    付け直したい時は --overwrite を付ける。
  ・**同じコードが2つの仕入先に付く場合は書き込まない**(コード順に並べた時に
    見分けが付かなくなるため)。該当は一覧に出す。
  ・書き込む前にバックアップを取る(scripts/backup_db.py と同じ場所)。
  ・個人情報は扱わない(仕入先名とコードだけ)。
"""
import argparse
import csv
import os
import shutil
import sqlite3
import sys
import time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402  CSVフォルダの探し方を取込と共通にする

SRC = _paths.csv_dir(os.path.join(BASE, "data", "real"))


def open_csv(name):
    """宝飾ナビのCSVを開く(BOM付きUTF-8優先。import_csv.py と同じ読み方)。"""
    path = os.path.join(SRC, name + ".csv")
    if not os.path.exists(path):
        return None
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            f = open(path, "r", encoding=enc, newline="")
            f.readline()
            f.seek(0)
            return f
        except UnicodeDecodeError:
            f.close()
    return open(path, "r", encoding="cp932", errors="replace", newline="")


def pick(row, want, suffix):
    """列名が想定と違っても拾う(import_csv.lookup と同じ考え方)。"""
    if want in row:
        return row[want]
    for k in row:
        if k and k.lower().endswith(suffix):
            return row[k]
    return None


def norm(s):
    return str(s or "").replace("　", " ").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="実際に書き込む(既定は下読み)")
    ap.add_argument("--overwrite", action="store_true",
                    help="既にコードが入っている仕入先も上書きする")
    a = ap.parse_args()

    if not os.path.exists(DB):
        print(f"DBがありません: {DB}")
        return 1
    f = open_csv("m_siiresaki")
    if f is None:
        print(f"m_siiresaki.csv が見つかりません: {SRC}")
        print("  宝飾ナビのCSVを data/real/csv/ に置いてから実行してください。")
        return 1

    # ── CSVから「名前 → コード」を作る ──
    by_name, dup_name = {}, {}
    n_csv = 0
    with f:
        for r in csv.DictReader(f):
            code = norm(pick(r, "strsircode", "code"))
            name = norm(pick(r, "strsirname", "name"))
            if not code or not name:
                continue
            n_csv += 1
            if name in by_name and by_name[name] != code:
                dup_name.setdefault(name, {by_name[name]}).add(code)
            else:
                by_name.setdefault(name, code)
    print(f"m_siiresaki.csv: {n_csv:,}件 / 名前の種類 {len(by_name):,}")
    if dup_name:
        print(f"  ※同じ名前に別のコードが付いている仕入先が {len(dup_name)}件あります"
              f"(最初のコードを使います)")
        for nm, codes in list(dup_name.items())[:5]:
            print(f"    {nm}: {sorted(codes)}")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    sys.path.insert(0, os.path.join(BASE, "server"))
    import db_query  # noqa: E402  ensure_schema で code 列を作る
    db_query.ensure_schema(con)

    cur = [dict(r) for r in con.execute(
        "SELECT name, code FROM supplier_master ORDER BY name")]
    print(f"仕入先マスタ: {len(cur):,}件"
          f"(うちコードあり {sum(1 for r in cur if r['code']):,}件)")

    # ── 突き合わせ ──
    plan, skip_has, not_found = [], [], []
    for r in cur:
        code = by_name.get(r["name"])
        if not code:
            not_found.append(r["name"])
            continue
        if r["code"] and not a.overwrite:
            if r["code"] != code:
                skip_has.append((r["name"], r["code"], code))
            continue
        if r["code"] == code:
            continue
        plan.append((r["name"], code))

    # ★同じコードが2つ以上に付く場合は入れない(並べた時に見分けが付かなくなる)
    used = {r["code"]: r["name"] for r in cur if r["code"]}
    seen, conflicts, ok_plan = {}, [], []
    for name, code in plan:
        owner = seen.get(code) or (used.get(code) if used.get(code) != name else None)
        if owner:
            conflicts.append((code, owner, name))
        else:
            seen[code] = name
            ok_plan.append((name, code))

    print()
    print(f"  埋められる            : {len(ok_plan):,}件")
    print(f"  CSVに名前が無い       : {len(not_found):,}件（コードは空のまま）")
    print(f"  既にコードあり(据置)  : {len(skip_has):,}件")
    print(f"  ★コードが重なるため保留: {len(conflicts):,}件")
    for c, o, n2 in conflicts[:10]:
        print(f"      コード {c} … 「{o}」と「{n2}」")
    if not_found[:10]:
        print("  CSVに見つからなかった仕入先(先頭10件):")
        for nm in not_found[:10]:
            print(f"      {nm}")

    if not a.apply:
        print("\n下読みだけで終了しました。書き込むには --apply を付けてください。")
        con.close()
        return 0
    if not ok_plan:
        print("\n書き込む内容がありません。")
        con.close()
        return 0

    # ── バックアップしてから書き込む ──
    bdir = os.path.join(BASE, "db", "backups")
    os.makedirs(bdir, exist_ok=True)
    bak = os.path.join(bdir, "tokiwa_仕入先コード前_%s.db" % time.strftime("%Y%m%d_%H%M%S"))
    con.close()
    shutil.copy2(DB, bak)
    print(f"\nバックアップ: {bak}")
    con = sqlite3.connect(DB)
    con.executemany("UPDATE supplier_master SET code=? WHERE name=?",
                    [(c, n2) for n2, c in ok_plan])
    con.commit()
    left = con.execute("SELECT COUNT(*) FROM supplier_master WHERE COALESCE(code,'')=''").fetchone()[0]
    print(f"{len(ok_plan):,}件にコードを入れました。コードが空のままの仕入先: {left:,}件")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
