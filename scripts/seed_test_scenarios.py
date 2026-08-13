#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""既存のDB(実データ)を消さずに、最終テスト用のシナリオだけを追加する。

背景(2026-08-13):
  最終テストは店の実データDBで行う(8月末に完全再移行するため、今のデータは
  どうなっても良い、という店の判断)。make_sample_data.py はDBを作り直してしまうので、
  実データを残したままテスト用ペルソナ(9001〜9008)だけを注入するのがこのスクリプト。

  何度実行してもよい(先に自分が入れた分を消してから入れ直す=冪等)。
  実データの顧客IDは「01-1234」形式なので、9001〜9008(ハイフン無し)とは衝突しない。
  商品キーは実データと重ならないよう「TEST-」で始める。伝票は slip_no に TEST- 印を付ける。

使い方(店のPC): python3 scripts/seed_test_scenarios.py → サーバー再起動 or F5

入れるもの(チェックリスト冒頭の表と同じ):
  9001 誕生日 未来子   … §20 今月の誕生日
  9002 記念日 夫婦子   … §20 結婚記念日
  9003 失効 間近子     … §20 ポイント失効(5日後・1,200pt)
  9004 納期 遅男       … §20 修理納期(2日遅れ+3日後)
  9005 死去 出ない子   … §7/§20 住所ＳＳＳ→出ない
  9006 送らない 子     … §7 DM区分=送らない
  9007 電話 なし子     … §7-9 B2の電話なし除外
  9008 返品 予定子     … §11-2 昨日の売上¥150,000(今日取消して日またぎ返品を検証)
  商品番号90001の2商品(TEST-A売上済/TEST-B在庫) … v0.34.9 同番号の検証
※実データにも本物の誕生日・ＴＴＴ住所・納期遅れ等があるので、そちらでも検証できる。
  このペルソナは「必ず存在する決め打ちのケース」として使う。
"""
import datetime
import os
import sqlite3
import sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")

STAFF_NAME = None   # 実データの担当者を1人使う(下で自動選択)


def main():
    if not os.path.exists(DB):
        sys.exit(f"[エラー] DBがありません: {DB}")
    con = sqlite3.connect(DB)
    cur = con.cursor()

    today = datetime.date.today()
    TODAY = today.isoformat()
    yesterday = (today - datetime.timedelta(days=1)).isoformat()

    def mday(offset):
        return f"{today.year:04d}-{today.month:02d}-{min(28, today.day + offset):02d}"

    # 実在の担当者名を1人拝借(お声がけ・伝票の担当表示用)
    row = cur.execute("SELECT name FROM staff WHERE COALESCE(name,'')<>'' LIMIT 1").fetchone()
    staff = row[0] if row else "テスト担当"

    # ── 冪等化: 前回このスクリプトが入れた分を消す ──
    ids = [str(i) for i in range(9001, 9009)]
    ph = ",".join("?" * len(ids))
    old_slips = [r[0] for r in cur.execute(
        "SELECT slip_id FROM sales_slips WHERE slip_no LIKE 'TEST-%'")]
    if old_slips:
        ph2 = ",".join("?" * len(old_slips))
        cur.execute(f"DELETE FROM sale_lines WHERE slip_id IN ({ph2})", old_slips)
        cur.execute(f"DELETE FROM sale_payments WHERE slip_id IN ({ph2})", old_slips)
        cur.execute(f"DELETE FROM sales_slips WHERE slip_id IN ({ph2})", old_slips)
    cur.execute(f"DELETE FROM repairs WHERE customer_id IN ({ph})", ids)
    cur.execute(f"DELETE FROM point_balances WHERE customer_id IN ({ph})", ids)
    cur.execute(f"DELETE FROM point_transactions WHERE customer_id IN ({ph})", ids)
    cur.execute(f"DELETE FROM approach_history WHERE customer_id IN ({ph})", ids)
    cur.execute(f"DELETE FROM customers WHERE customer_id IN ({ph})", ids)
    cur.execute("DELETE FROM products WHERE product_key LIKE 'TEST-%'")

    def add_customer(cid, name, kana, birthday=None, wedding=None, note=None,
                     addr="豊田市桜町1-1", tel="0565-00-0000", dm=None):
        cur.execute("""INSERT INTO customers(customer_id,name,kana,tel,gender,birthday,wedding_day,
                       postal,address,staff_name,dm_ok,is_test,note)
                       VALUES (?,?,?,?,'女',?,?,?,?,?,?,1,?)""",
                    (cid, name, kana, tel, birthday, wedding, "471-0000", addr, staff, dm, note))

    # §20 お声がけ
    add_customer("9001", "誕生日 未来子", "ﾀﾝｼﾞｮｳﾋﾞ ﾐｷｺ", birthday=f"1970-{mday(5)[5:]}",
                 note="テスト用: 今月の誕生日がお声がけに出る")
    add_customer("9002", "記念日 夫婦子", "ｷﾈﾝﾋﾞ ﾌｳﾌｺ", birthday="1965-01-10",
                 wedding=f"1990-{mday(2)[5:]}", note="テスト用: 結婚記念日")
    add_customer("9003", "失効 間近子", "ｼｯｺｳ ﾏｼﾞｶｺ", birthday="1972-02-02",
                 note="テスト用: ポイント失効間近(5日後)")
    expiry_target = today + datetime.timedelta(days=5)
    try:
        old_buy = expiry_target.replace(year=expiry_target.year - 5).isoformat()
    except ValueError:
        old_buy = expiry_target.replace(year=expiry_target.year - 5, day=28).isoformat()
    cur.execute("""INSERT INTO sales_slips(slip_no,customer_id,staff_name,sold_at,pay_method)
                   VALUES ('TEST-9101','9003',?,?,'現金')""", (staff, old_buy))
    sid = cur.lastrowid
    cur.execute("INSERT INTO sale_lines(slip_id,free_name,amount) VALUES (?,?,80000)", (sid, "昔の指輪"))
    cur.execute("INSERT OR REPLACE INTO point_balances(customer_id,balance,updated_at) VALUES ('9003',1200,?)",
                (old_buy,))
    add_customer("9004", "納期 遅男", "ﾉｳｷ ｵｸﾚｵ", birthday="1960-03-03",
                 note="テスト用: 修理納期(遅れ+3日後)")
    cur.execute("""INSERT INTO repairs(repair_no,customer_id,item_name,issue,estimate,received_at,
                   promised_at,status,staff_name,note) VALUES ('TEST-R1','9004','ネックレス糸替え',
                   '糸のゆるみ',2000,?,?,'修理中',?, '納期超過の表示確認')""",
                (yesterday, (today - datetime.timedelta(days=2)).isoformat(), staff))
    cur.execute("""INSERT INTO repairs(repair_no,customer_id,item_name,issue,estimate,received_at,
                   promised_at,status,staff_name) VALUES ('TEST-R2','9004','指輪サイズ直し',
                   '9号→11号',3000,?,?,'預かり中',?)""",
                (yesterday, (today + datetime.timedelta(days=3)).isoformat(), staff))
    # §7 DM不可・B2
    add_customer("9005", "死去 出ない子", "ｼｷｮ ﾃﾞﾅｲｺ", birthday=f"1940-{mday(3)[5:]}",
                 addr="ＳＳＳ豊田市桜町1-5", note="テスト用: 住所ＳＳＳ→ラベル・B2・お声がけに出ない")
    add_customer("9006", "送らない 子", "ｵｸﾗﾅｲ ｺ", birthday=f"1955-{mday(4)[5:]}",
                 dm="送らない", note="テスト用: DM区分=送らない")
    add_customer("9007", "電話 なし子", "ﾃﾞﾝﾜ ﾅｼｺ", birthday="1985-05-05",
                 tel=None, note="テスト用: B2で電話なし→除外案内")
    # §11 日またぎ返品 + 同番号2商品(v0.34.9)
    add_customer("9008", "返品 予定子", "ﾍﾝﾋﾟﾝ ﾖﾃｲｺ", birthday="1978-06-06",
                 note="テスト用: 昨日の売上¥150,000を今日取消す(日またぎ返品)")
    cur.execute("""INSERT INTO products(product_key,product_no,name,category,list_price,cost_price,state,center_stone)
                   VALUES ('TEST-A','90001','ダイヤリングA(同番号テスト)','宝石',150000,60000,'売上','ダイヤ')""")
    cur.execute("""INSERT INTO products(product_key,product_no,name,category,list_price,cost_price,state,center_stone)
                   VALUES ('TEST-B','90001','ルビーリングB(同番号テスト)','宝石',80000,30000,'在庫','ルビー')""")
    cur.execute("""INSERT INTO sales_slips(slip_no,customer_id,staff_name,sold_at,pay_method)
                   VALUES ('TEST-9102','9008',?,?,'現金')""", (staff, yesterday))
    sid = cur.lastrowid
    cur.execute("INSERT INTO sale_lines(slip_id,product_key,list_price,amount) VALUES (?,'TEST-A',150000,150000)", (sid,))
    cur.execute("INSERT INTO sale_payments(slip_id,method,amount) VALUES (?,'現金',150000)", (sid,))

    con.commit()
    n = cur.execute(f"SELECT COUNT(*) FROM customers WHERE customer_id IN ({ph})", ids).fetchone()[0]
    con.close()
    print(f"テスト用シナリオを追加しました(顧客{n}人・商品2点・昨日の売上1件・修理2件)。")
    print("既存のデータは一切消していません。もう一度実行すると入れ直しになります(冪等)。")
    print("サーバーを再起動(またはブラウザをF5)してから、ホームのお声がけ・§11の返品を確認してください。")


if __name__ == "__main__":
    main()
