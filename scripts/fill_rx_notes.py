# -*- coding: utf-8 -*-
"""処方箋の「メモ」を、宝飾ナビの**アイ備考2**(d_shohosen.strbiko2)から埋める(2026-09-19)。

作った理由:
  店から「処方箋にメモが残せる欄ってあったっけ?」と聞かれ、無いことが分かった
  (処方箋は度数・PD・視力・金額の欄しかなく、自由に書ける欄が1つも無かった)。
  さらに「宝飾ナビには**アイ備考2**という名前である」と教わり、台帳の棚卸しで
  **50,413件中 41.3%(約2万件)に値が入っている**ことを確認した。
  見本: 「平岩商店 娘様」「ｸﾘｽﾀﾙｶｯﾄ ﾏﾂｼﾏﾔ水野様の妹」「検梅村」
  → 紹介者・ご続柄・検査した人などの覚え書きで、**トキワにはどこにも入っていなかった**。
  v1.5.6 で `prescriptions.note` を作ったので、このスクリプトで過去ぶんを入れる。

どの処方箋に入れるかの決め方(★ここが肝):
  宝飾ナビの処方箋の主キー(lngshohosenid)はトキワに取り込んでいないため、
  **中身の組み合わせ**で突き合わせる:
      顧客ID / 処方箋No / 処方日 / レンズのキー / フレームのキー
  ★どちらか片方でも**同じ組み合わせが2件以上ある**ものは、取り違えると直せないので
    **入れずに数える**(「判別できない」として下読みに出す)。
    出過ぎるのは選べば済むが、間違った人のメモが入るのは取り返しがつかない。

確認のしかた(2026-09-19 店の要望で追加):
  下読みに**確認用の見本**(顧客ID と 処方箋No)を数件ずつ出す。★**入れる前に**その方を
  宝飾ナビで開き、アイ備考2の中身と突き合わせられる(=正しいと分かってから入れられる)。
  「見つからない」の見本は、突き合わせのどこがずれているかを調べる手がかりになる。

★安全のための決まり:
  ・既定は「下読み」。何件入るかを出すだけで、データは1文字も変更しない。
  ・書き込むのは --apply を付けた時だけ。その直前に必ずバックアップを取る。
  ・**すでにメモが入っている処方箋は触らない**(店が手で書いた値を消さないため)。
  ・個人情報は出さない。★メモの中身にはお客様のお名前が入っているので、
    **中身は1文字も画面に出さない**(件数と、長さの分布だけ)。

中身の掃除:
  ・前後の空白を落とす
  ・中身が「0」だけ(や空)の行は**入れない**。宝飾ナビは未入力を 0 で埋めることがあり、
    そのまま入れると「0」とだけ書かれた処方箋が大量にできてしまう。
  ・見本に「0 ｸﾘｽﾀﾙｶｯﾄ …」のように**先頭に「0 」が付いた値**があった。意味のある値かも
    しれないので**既定では落とさない**(件数だけ下読みに出す)。落としたい時は --trim0。
  ・半角カナはそのまま入れる(商品名など他の移行データと同じ見た目にするため)。

使い方:
  py -3 scripts\\fill_rx_notes.py                  # 下読み(何件入るか見るだけ)
  py -3 scripts\\fill_rx_notes.py --apply          # バックアップしてから書き込む
  py -3 scripts\\fill_rx_notes.py --trim0          # 先頭の「0 」を落とす(下読み)
  py -3 scripts\\fill_rx_notes.py --apply --trim0  # 落として書き込む
"""
import argparse
import collections
import csv
import os
import re
import shutil
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..")
DB = os.path.join(BASE, "db", "tokiwa.db")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(BASE, "server"))
import _paths      # noqa: E402
import db_query    # noqa: E402

REAL_BASE = os.path.join(BASE, "data", "real")


def s(v):
    """前後の空白(全角も)を落とす。無ければ None。"""
    if v is None:
        return None
    t = str(v).replace("　", " ").strip()
    return t or None


def dt(v):
    """日付文字列 → YYYY-MM-DD。★取込(import_csv.dt)と同じ形にしないと突き合わない。"""
    t = s(v)
    if not t:
        return None
    m = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", t)
    return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3))) if m else None


def pair(r, tc, kc):
    """店舗コードとキーを「01-1234」の形にする(取込と同じ作り方)。"""
    t, k = s(r.get(tc)), s(r.get(kc))
    return ("%s-%s" % (t, k)) if (t and k) else None


def clean_note(raw, trim0):
    """メモとして入れてよい値に整える。入れないものは None を返す。
    戻り (値 or None, 先頭が「0 」だったか)。"""
    t = s(raw)
    if not t:
        return None, False
    lead0 = bool(re.match(r"^0\s+\S", t))
    if trim0 and lead0:
        t = t[1:].strip()
    # 中身が 0 や 0.0 や「0 0」のように**数字のゼロと空白だけ**なら意味がない
    if re.fullmatch(r"[0\s.]+", t):
        return None, lead0
    return t, lead0


SAMPLE = 5     # 確認用に出す見本の数


def sample_text(keys):
    """確認用の見本を「顧客ID(処方箋No / 処方日)」の形で数件ならべる。
    ★顧客IDと処方箋Noだけ。氏名もメモの中身も出さない。
      顧客管理の検索箱に顧客IDをそのまま入れると、その方を開ける。"""
    out = []
    for k in list(keys)[:SAMPLE]:
        out.append("%s(処方箋No %s / %s)" % (k[0] or "?", k[1] or "?", k[2] or "日付なし"))
    return " / ".join(out) if out else "(なし)"


def stream(path):
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            f = open(path, "r", encoding=enc, newline="")
            f.readline()
            f.seek(0)
            break
        except UnicodeDecodeError:
            continue
    else:
        print("  [読めません] %s" % path)
        return
    try:
        for row in csv.DictReader(f):
            yield row
    finally:
        f.close()


def main():
    ap = argparse.ArgumentParser(description="処方箋のメモを宝飾ナビのアイ備考2から埋める(既定は下読み)")
    ap.add_argument("--apply", action="store_true", help="実際に書き込む(既定は下読みのみ)")
    ap.add_argument("--trim0", action="store_true", help="先頭の「0 」を落とす(既定は落とさない)")
    a = ap.parse_args()

    if not os.path.exists(DB):
        print("DBが見つかりません: %s" % DB)
        return 1
    csv_dir = _paths.find_dir(REAL_BASE, "*.csv", "csv")
    path = os.path.join(csv_dir, "d_shohosen.csv")
    if not os.path.exists(path):
        print("元CSVが見つかりません: %s" % path)
        return 1

    print("読むだけの下読みです(--apply を付けるまでデータは変更しません)。" if not a.apply
          else "書き込みます(直前にバックアップを取ります)。")
    print("元CSV: %s" % path)
    print("★メモの中身にはお客様のお名前が入るため、中身は1文字も表示しません。\n")

    # ── 1. 元CSVを読んで「鍵 → メモ」を作る ──────────────────────────
    plan, dup_csv = {}, set()
    n_rows = n_blank = n_zero = n_lead0 = 0
    for r in stream(path):
        n_rows += 1
        note, lead0 = clean_note(r.get("strbiko2"), a.trim0)
        if lead0:
            n_lead0 += 1
        if note is None:
            if s(r.get("strbiko2")) is None:
                n_blank += 1
            else:
                n_zero += 1
            continue
        key = (pair(r, "strkotencode", "lngkokey"), s(r.get("lngshohosenno")),
               dt(r.get("datinpdate")), pair(r, "strsytencode1", "lngsykey1"),
               pair(r, "strsytencode2", "lngsykey2"))
        if key in plan:
            dup_csv.add(key)          # 同じ組み合わせが2件以上 = どちらのメモか決められない
        plan[key] = note
    for k in dup_csv:
        plan.pop(k, None)

    print("■ 元CSV(d_shohosen %s行)" % format(n_rows, ","))
    print("  ・アイ備考2に文字がある      : %s件" % format(n_rows - n_blank - n_zero, ","))
    print("  ・空欄                       : %s件" % format(n_blank, ","))
    print("  ・中身が「0」だけ(入れません): %s件" % format(n_zero, ","))
    print("  ・先頭が「0 」で始まる       : %s件 %s"
          % (format(n_lead0, ","), "(--trim0 で落としました)" if a.trim0 else "(そのまま入れます。落とすなら --trim0)"))
    if dup_csv:
        print("  ★同じ組み合わせが2件以上あり判別できない: %s件(入れません)" % format(len(dup_csv), ","))
        print("     確認用: %s" % sample_text(dup_csv))

    # ── 2. トキワ側の処方箋を同じ鍵で引けるようにする ────────────────
    con = sqlite3.connect(DB)
    db_query.ensure_schema(con)        # note 列が無いDBでも動くように
    con.row_factory = sqlite3.Row
    index, dup_db = {}, set()
    have_note = 0
    for r in con.execute("""SELECT id, customer_id, rx_no, rx_date, lens_key, frame_key,
                                   COALESCE(note,'') note FROM prescriptions"""):
        if r["note"].strip():
            have_note += 1
        key = (r["customer_id"], s(r["rx_no"]), s(r["rx_date"]), s(r["lens_key"]), s(r["frame_key"]))
        if key in index:
            dup_db.add(key)
        index[key] = (r["id"], r["note"].strip())
    for k in dup_db:
        index.pop(k, None)

    # 「見つからない」の中身を分けるため、トキワに居るお客様の一覧も持っておく
    db_cust = set(r[0] for r in con.execute("SELECT customer_id FROM customers"))
    total_rx = con.execute("SELECT COUNT(*) FROM prescriptions").fetchone()[0]
    print("\n■ トキワの処方箋: %s件(うち既にメモがある: %s件)"
          % (format(total_rx, ","), format(have_note, ",")))
    if dup_db:
        print("  ★同じ組み合わせが2件以上ある処方箋: %s件(入れません)" % format(len(dup_db), ","))
        print("     確認用: %s" % sample_text(dup_db))

    # ── 3. 突き合わせ ──────────────────────────────────────────
    todo, skip_have, miss = [], 0, 0
    miss_nocust = miss_key = 0
    ex_todo, ex_have, ex_miss = [], [], []    # 確認用の見本(顧客IDと処方箋Noだけ)
    lens = collections.Counter()
    for key, note in plan.items():
        hit = index.get(key)
        if not hit:
            miss += 1
            # ★「入れ先が無い」には2種類ある。分けないと手の打ちようが分からない:
            #   (1) そのお客様自体がトキワに居ない … 宝飾ナビ側で顧客が消された孤児データ。
            #       処方箋ごと取り込めていないので、メモだけ入れる先が無い(諦めるしかない)
            #   (2) お客様は居るのに処方箋が見つからない … 突き合わせのずれ。直せる可能性がある
            if key[0] not in db_cust:
                miss_nocust += 1
            else:
                miss_key += 1
                if len(ex_miss) < SAMPLE:
                    ex_miss.append(key)
            continue
        rx_id, cur_note = hit
        if cur_note:
            skip_have += 1        # ★手で書いたメモは消さない
            if len(ex_have) < SAMPLE:
                ex_have.append(key)
            continue
        todo.append((note, rx_id))
        if len(ex_todo) < SAMPLE:
            ex_todo.append(key)
        lens["〜20文字" if len(note) <= 20 else ("21〜50文字" if len(note) <= 50 else "51文字〜")] += 1

    print("\n■ 突き合わせの結果")
    print("  ★入れられる                  : %s件" % format(len(todo), ","))
    print("     確認用: %s" % sample_text(ex_todo))
    print("  ・すでにメモがある(触りません): %s件" % format(skip_have, ","))
    if skip_have:
        print("     確認用: %s" % sample_text(ex_have))
    print("  ・トキワ側に見つからない      : %s件" % format(miss, ","))
    if miss:
        print("     うち お客様自体がトキワに居ない: %s件" % format(miss_nocust, ","))
        print("       → 宝飾ナビ側で顧客が消された孤児データ。処方箋ごと取り込めていないので")
        print("         入れる先がありません(想定どおり。手の打ちようはありません)")
        print("     うち お客様は居るのに処方箋が合わない: %s件" % format(miss_key, ","))
        if miss_key:
            print("       確認用: %s" % sample_text(ex_miss))
            print("       ※★こちらは突き合わせのずれです。この方を宝飾ナビとトキワの両方で開いて")
            print("         見比べると、どこ(処方箋No/処方日/レンズ/フレーム)がずれているか分かります。")
    if todo:
        print("  ・長さの内訳: " + " / ".join("%s %s件" % (k, format(v, ",")) for k, v in lens.most_common()))
    print("\n  ※確認のしかた: 顧客管理の検索箱に**顧客IDをそのまま**入れて開き、")
    print("    「メガネ(処方箋)」タブでその処方箋Noの行を開くとメモが出ます。")
    print("    ★検索の**店舗は「全店」**にしてください(処方箋のお客様は 99- が多く、")
    print("      既定の「01 本店」では出ません)。")

    if not a.apply:
        print("\n下読みだけで終了しました。書き込むには --apply を付けてください。")
        con.close()
        return 0
    if not todo:
        print("\n入れるものがありません。")
        con.close()
        return 0

    bdir = os.path.join(BASE, "db", "backups")
    os.makedirs(bdir, exist_ok=True)
    bak = os.path.join(bdir, "tokiwa_処方箋メモ前_%s.db" % time.strftime("%Y%m%d_%H%M%S"))
    con.close()
    shutil.copy2(DB, bak)
    print("\nバックアップ: %s" % bak)
    con = sqlite3.connect(DB)
    con.executemany("UPDATE prescriptions SET note=? WHERE id=? AND COALESCE(note,'')=''", todo)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM prescriptions WHERE COALESCE(note,'')<>''").fetchone()[0]
    print("書き込み完了。メモのある処方箋: %s件 になりました。" % format(n, ","))
    print("顧客詳細の「メガネ(処方箋)」を開き直すと、処方箋を開いた時にメモが出ます。")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
