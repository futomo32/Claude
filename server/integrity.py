# -*- coding: utf-8 -*-
"""トキワ データ点検(整合性チェック)。誤削除・破損・数字の狂いを早く見つけるための診断。

「壊れた」は検知できるが「誤って消した」の意図は判定できない。そのため:
- 構造の破損 …… PRAGMA quick_check(重い integrity_check は backup.py がコピーに対して毎日実行)
- 参照切れ   …… PRAGMA foreign_key_check(SQLiteは既定で外部キーを強制しないため、後から検査する)
- 業務ルールの矛盾 …… 残高と履歴の突き合わせ・マイナス金額・空伝票・在庫の二重販売
の3階層で「おかしくなっていること」を見つける。件数の急減(誤削除の兆候)は backup.py 側で見る。

★個人情報は出力しない(顧客名は出さず、必要な場合も顧客IDまで)。画面・ログに出すため。
★移行データ由来の不一致が最初から存在する場合がある(ポイント残高など)。初回の結果を
  「基準値」として把握し、そこから増えたかどうかで判断する。
"""
import datetime
import sqlite3

SAMPLE_MAX = 5   # 例として出す件数(多すぎると画面が埋まる)


def _count(con, sql, args=()):
    try:
        row = con.execute(sql, args).fetchone()
        return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return -1   # テーブルが無い等。点検不能として扱う


def _check(name, count, level, detail="", hint=""):
    return {"name": name, "count": count, "level": level, "detail": detail, "hint": hint}


def check_structure(con):
    """構造の破損(軽量版)。重い全チェックはバックアップ時にコピーへ実行している。"""
    try:
        row = con.execute("PRAGMA quick_check").fetchone()
        msg = str(row[0]) if row else ""
        if msg.lower() == "ok":
            return _check("DBファイルの構造", 0, "ok")
        return _check("DBファイルの構造", 1, "error", msg[:200],
                      "バックアップからの復元を検討してください(docs/backup.md)")
    except sqlite3.Error as e:
        return _check("DBファイルの構造", 1, "error", str(e)[:200])


def check_foreign_keys(con):
    """参照切れ(孤児データ)。宣言はあるがSQLiteは既定で強制しないため後から検査する。"""
    try:
        rows = con.execute("PRAGMA foreign_key_check").fetchall()
    except sqlite3.Error as e:
        return _check("参照切れ(孤児データ)", -1, "warn", str(e)[:200])
    if not rows:
        return _check("参照切れ(孤児データ)", 0, "ok")
    tables = {}
    for r in rows:
        tables[r[0]] = tables.get(r[0], 0) + 1
    detail = "・".join(f"{t} {n}件" for t, n in sorted(tables.items(), key=lambda x: -x[1])[:SAMPLE_MAX])
    return _check("参照切れ(孤児データ)", len(rows), "warn", detail,
                  "移行データ由来の場合があります。初回の件数から増えていなければ様子見で可")


def check_empty_slips(con):
    """明細が1件も無い売上伝票。誤削除・処理中断の痕跡として現れる。"""
    n = _count(con, """SELECT COUNT(*) FROM sales_slips s
                       WHERE COALESCE(s.voided,0)=0
                         AND NOT EXISTS (SELECT 1 FROM sale_lines l
                                         WHERE l.slip_id=s.slip_id AND COALESCE(l.voided,0)=0)""")
    return _check("明細が空の売上伝票", n, "ok" if n == 0 else "warn", "",
                  "明細だけ消えた可能性。伝票番号を確認し、レシート控えと突き合わせてください")


def check_negatives(con):
    """マイナス値の異常。返品は取消フラグで表すため、金額や残高がマイナスなのは異常。"""
    parts, total = [], 0
    for label, sql in (
        ("ポイント残高", "SELECT COUNT(*) FROM point_balances WHERE balance < 0"),
        ("売掛残高", "SELECT COUNT(*) FROM receivables WHERE balance < 0"),
        ("売上明細の金額", "SELECT COUNT(*) FROM sale_lines WHERE COALESCE(voided,0)=0 AND amount < 0"),
    ):
        n = _count(con, sql)
        if n > 0:
            parts.append(f"{label} {n}件")
            total += n
    return _check("マイナス値の異常", total, "ok" if total == 0 else "error", "・".join(parts),
                  "計算処理の不具合か手修正の誤り。該当行を特定して修正してください")


def check_point_balance(con):
    """ポイント残高と履歴の合計が一致するか。残高だけ書き換わった事故を検知できる。"""
    try:
        rows = con.execute("""
            SELECT b.customer_id, b.balance,
                   SUM(COALESCE(t.points, COALESCE(t.add_points,0) - COALESCE(t.use_points,0))) calc
            FROM point_balances b
            JOIN point_transactions t ON t.customer_id = b.customer_id
            GROUP BY b.customer_id, b.balance
            HAVING b.balance <> calc""").fetchall()
    except sqlite3.Error as e:
        return _check("ポイント残高と履歴の一致", -1, "warn", str(e)[:200])
    if not rows:
        return _check("ポイント残高と履歴の一致", 0, "ok")
    # 顧客名は出さない(個人情報)。IDと差額だけを例示する
    ex = "・".join(f"ID {r[0]}(残高{r[1]:,}/履歴{int(r[2] or 0):,})" for r in rows[:SAMPLE_MAX])
    return _check("ポイント残高と履歴の一致", len(rows), "warn", ex,
                  "移行時点から不一致がある場合あり。初回の件数を基準にし、増えたら調査")


def check_double_sale(con):
    """同じ在庫品(1点もの)が2回以上売れている状態。レジ側で防いでいるが念のため検査する。"""
    try:
        rows = con.execute("""
            SELECT l.product_key, COUNT(*) c
            FROM sale_lines l JOIN sales_slips s ON s.slip_id = l.slip_id
            WHERE l.product_key IS NOT NULL
              AND COALESCE(l.voided,0)=0 AND COALESCE(s.voided,0)=0
            GROUP BY l.product_key HAVING c > 1""").fetchall()
    except sqlite3.Error as e:
        return _check("在庫品の二重販売", -1, "warn", str(e)[:200])
    if not rows:
        return _check("在庫品の二重販売", 0, "ok")
    ex = "・".join(f"{r[0]}({r[1]}回)" for r in rows[:SAMPLE_MAX])
    return _check("在庫品の二重販売", len(rows), "warn", ex,
                  "移行データに元々含まれる場合あり。新しく増えた場合は返品処理の漏れを確認")


CHECKS = (check_structure, check_foreign_keys, check_empty_slips,
          check_negatives, check_point_balance, check_double_sale)


def run(db_path):
    """全項目を点検して結果を返す。画面表示とコンソール出力にそのまま使える形。"""
    at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = {"at": at, "ok": True, "checks": [], "summary": ""}
    try:
        con = sqlite3.connect(db_path)
    except sqlite3.Error as e:
        out["ok"] = False
        out["summary"] = f"DBを開けません: {e}"
        return out
    try:
        for fn in CHECKS:
            try:
                out["checks"].append(fn(con))
            except Exception as e:  # noqa: BLE001 1項目の失敗で点検全体を止めない
                out["checks"].append(_check(getattr(fn, "__name__", "点検"), -1, "warn", str(e)[:200]))
    finally:
        con.close()
    errors = [c for c in out["checks"] if c["level"] == "error"]
    warns = [c for c in out["checks"] if c["level"] == "warn" and c["count"] != 0]
    out["ok"] = not errors and not warns
    if errors:
        out["summary"] = "要対応 " + "・".join(f"{c['name']}{c['count']}件" for c in errors)
        if warns:
            out["summary"] += " / 注意 " + "・".join(f"{c['name']}{c['count']}件" for c in warns)
    elif warns:
        out["summary"] = "注意 " + "・".join(f"{c['name']}{c['count']}件" for c in warns)
    else:
        out["summary"] = "異常なし(全項目OK)"
    return out


def run_and_record(db_path, con=None):
    """点検を実行し、結果をDBに記録する(画面の「最終点検」に出す)。"""
    result = run(db_path)
    if con is not None:
        import db_query  # 遅延import(このモジュール単体でもテストできるようにする)
        db_query.record_integrity_result(con, result["at"], result["summary"], result["checks"])
    return result
