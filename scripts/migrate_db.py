# -*- coding: utf-8 -*-
"""既存DBに後付けした列を追加する軽量マイグレーション(冪等・再取込不要)。

スキーマは「列は後から ALTER TABLE ADD COLUMN で拡張する前提」(db/schema.sql)。
機能追加で列が増えたのに、DBが古いまま(その列が無い)だと、サーバー起動時に
build_blob が `no such column` で落ちる。このツールは不足している既知の列だけを
足して、DBを作り直さずに最新のコードで動くようにする。

  python3 scripts/migrate_db.py            # db/tokiwa.db に適用
  python3 scripts/migrate_db.py <db path>  # 別DBを指定

何度実行しても安全(既にある列はスキップ)。データは消さない。
"""
import os
import sqlite3
import sys

BASE = os.path.join(os.path.dirname(__file__), "..")
DB = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "db", "tokiwa.db")

# 後付けした列の一覧: (テーブル, 列名, 型宣言)
# ※FK(REFERENCES)は付けない。SQLiteのADD COLUMN制約回避＆本アプリはFK非強制のため
#   平のTEXT列で機能的に同等。既にある列は自動でスキップする。
EXPECTED_COLUMNS = [
    ("customer_families", "linked_customer_id", "TEXT"),  # 家族B(登録済み顧客と相互リンク)
    # 顧客の後付け列(古いDB救済用。既にあればスキップ)
    ("customers", "tel2", "TEXT"),
    ("customers", "note", "TEXT"),
    ("customers", "postal", "TEXT"),
    ("customers", "address2", "TEXT"),
    ("customers", "email", "TEXT"),
    ("products", "image_file", "TEXT"),   # 商品写真(B-7)
]


def table_exists(con, table):
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def columns_of(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def main():
    if not os.path.exists(DB):
        print(f"[エラー] DBがありません: {DB}")
        sys.exit(1)

    con = sqlite3.connect(DB)
    added, skipped, missing_tables = [], [], []
    try:
        for table, col, decl in EXPECTED_COLUMNS:
            if not table_exists(con, table):
                if table not in missing_tables:
                    missing_tables.append(table)
                continue
            if col in columns_of(con, table):
                skipped.append(f"{table}.{col}")
                continue
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            added.append(f"{table}.{col} ({decl})")
        con.commit()
    finally:
        con.close()

    print(f"■ マイグレーション対象DB: {DB}")
    if added:
        print(f"   追加した列 ({len(added)}):")
        for a in added:
            print(f"     + {a}")
    else:
        print("   追加した列: なし(すべて最新)")
    if skipped:
        print(f"   既にあった列: {len(skipped)} 件(スキップ)")
    if missing_tables:
        print(f"   [注意] テーブル自体が存在しません: {', '.join(missing_tables)}")
        print("     → DBがかなり古い可能性。scripts/import_csv.py で作り直しを検討してください。")
    print("\n完了。サーバー(トキワ起動.bat)や診断を再実行してください。")


if __name__ == "__main__":
    main()
