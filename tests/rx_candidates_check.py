# -*- coding: utf-8 -*-
"""処方箋の「購入データと紐付け」の候補の出し方を確かめる(v1.4.3)。

  python3 tests/rx_candidates_check.py

★ブラウザもサーバーも要らない。db/tokiwa.db を**コピーしてから**試すので、
  元のDBは一切変更しない(最後にコピーを消す)。
  それでも本番機では実行しないこと(テスト用のデータを作るため)。

見るもの(2026-09-05に直した3点):
  (1) マイナス金額(宝飾ナビの赤黒=打ち消しの行)を候補に出さない
  (2) 仕入先のジャンル(メガネ)でも判定する。品名が型番だけでも拾える
  (3) メガネと判定できなかった購入も候補に出す(下のグループ)。メガネの分が先に並ぶ
"""
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
import db_query  # noqa: E402

DB = os.path.join(HERE, "..", "db", "tokiwa.db")
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("  OK  " if ok else "★NG  ") + name + (("   … " + str(detail)) if detail else ""))


tmp = os.path.join(tempfile.mkdtemp(), "rx_check.db")
shutil.copy(DB, tmp)
try:
    c = sqlite3.connect(tmp)
    c.row_factory = sqlite3.Row
    cid = c.execute("SELECT customer_id FROM customers WHERE COALESCE(is_test,0)=0 LIMIT 1").fetchone()[0]
    slip = (c.execute("SELECT MAX(slip_id) FROM sales_slips").fetchone()[0] or 0) + 1
    c.execute("INSERT INTO sales_slips(slip_id,customer_id,sold_at,staff_name) VALUES (?,?,?,?)",
              (slip, cid, "2026-09-04", "テスト"))
    # メガネのメーカーを1つ作り、そこから仕入れた「型番だけの名前」の商品を用意する
    c.execute("INSERT OR REPLACE INTO supplier_master(name,genre) VALUES ('ﾃｽﾄ眼鏡商事','メガネ')")
    pk = "TESTRX1"
    c.execute("INSERT INTO products(product_key,product_no,name,supplier,state,is_glasses) "
              "VALUES (?,?,?,?,?,0)", (pk, "99991", "POLICE VPLP39J 07R5 48", "ﾃｽﾄ眼鏡商事", "売上"))
    lines = [
        ("POLICE VPLP39J 07R5 48", 15500, pk),     # 型番だけ＋メガネ仕入先 → 拾えるはず
        ("ｾﾝﾁｭﾘｰAIZ160-12ECC PBUV", 57500, None),  # 番号なし・型番だけ → 「その他」に出る
        ("52メガネセット", 14800, None),            # 名前で拾える
        ("52メガネセット", -14800, None),           # ★赤黒 → 出してはいけない
        ("ダイヤリング", 300000, None),             # メガネでない → 「その他」に出る
    ]
    for nm, amt, key in lines:
        c.execute("INSERT INTO sale_lines(slip_id,product_key,free_name,amount) VALUES (?,?,?,?)",
                  (slip, key, nm, amt))
    c.commit()

    cand = db_query.customer_detail(c, cid)["rxCandidates"]
    for x in cand:
        print("      %-28s ¥%-9s %s" % (x[2], x[3], "メガネ" if x[5] else "その他"))

    check("★マイナス金額(赤黒の打ち消し)は候補に出さない",
          not any((x[3] or 0) < 0 for x in cand),
          [x[2] for x in cand if (x[3] or 0) < 0])
    check("★仕入先のジャンルで、型番だけの名前でもメガネと分かる",
          any(x[2].startswith("POLICE") and x[5] == 1 for x in cand),
          [x for x in cand if x[2].startswith("POLICE")])
    check("名前に「メガネ」が入るものは今までどおり拾える",
          any("メガネセット" in x[2] and x[5] == 1 for x in cand))
    check("★メガネと判定できなかった購入も候補に出る(手で選べる)",
          any(x[2].startswith("ｾﾝﾁｭﾘｰ") and x[5] == 0 for x in cand),
          [x[2] for x in cand if x[5] == 0][:4])
    check("★メガネの分が先に並ぶ(その他は後ろ)",
          [x[5] for x in cand] == sorted([x[5] for x in cand], reverse=True),
          [x[5] for x in cand])
    check("行の形が [明細ID,買上日,品名,金額,frame/lens,メガネ判定] の6つ",
          all(len(x) == 6 for x in cand), len(cand[0]) if cand else 0)

    # 紐付け済みの明細は候補から消える
    line_id = cand[0][0]
    c.execute("INSERT INTO prescriptions(customer_id,sale_line_id,rx_date) VALUES (?,?,?)",
              (cid, line_id, "2026-09-04"))
    c.commit()
    again = db_query.customer_detail(c, cid)["rxCandidates"]
    check("紐付け済みの明細は候補から消える",
          all(x[0] != line_id for x in again), line_id)
    c.close()
finally:
    if os.path.exists(tmp):
        os.remove(tmp)
        os.rmdir(os.path.dirname(tmp))

ng = [r for r in results if not r[1]]
print("\n" + "=" * 56)
print("  %d項目中 %d項目OK / NG %d項目" % (len(results), len(results) - len(ng), len(ng)))
for n, _, d in ng:
    print("    ★ " + n + ("   " + str(d) if d else ""))
sys.exit(1 if ng else 0)
