# -*- coding: utf-8 -*-
"""宝飾ナビの列のうち「実際に値が入っているのに、トキワに持ってきていない」ものを洗い出す。

作った理由(2026-08-03):
  値札タグに刷る品番(d_siire.strsirsycode)とタグ品名(d_item.strtaghinname)が、
  トキワへの取込から漏れていた。宝飾ナビは1テーブル100列超あり、画面を触って探すのは
  現実的でない。8月末の実データ再取込より前に、他に漏れが無いかを機械的に確かめる。

やっていること:
  1. data/real/csv/ の各テーブルの全列について、値が入っている行の割合(入力率)を数える
  2. 値のサンプルと「値の形」(数字だけ/日付/カナ など)をまとめる
  3. トキワが取り込み済みと【確認できている】列に印を付け、それ以外を入力率の高い順に並べる
     (★「取り込み済み」の根拠は scripts/import_csv.py の実装。2026-08-06に全列を
       突き合わせて書き直した。import_csv.py を変えたらこの一覧も直すこと)

★「未確認」は「不要」ではない。単にこちらで対応を確認できていないだけ。
  入力率が高い未確認の列から順に、何の項目かを見ていくのが効率的。

使い方:
  python3 scripts/diag_unused_columns.py             # 主要テーブルだけ(既定)
  python3 scripts/diag_unused_columns.py --all       # 全テーブル
  python3 scripts/diag_unused_columns.py --min 30    # 入力率30%以上だけ表示(既定10%)
  python3 scripts/diag_unused_columns.py d_item      # テーブルを指定

出力:
  画面 … 未確認かつ入力率の高い列だけ(見やすさ優先)
  ファイル … data/real/未取込の列.txt に全列ぶん(gitignore下・GitHubには載りません)

個人情報:
  値のサンプルは _privacy.py の判定で伏せ字にする。列名と件数は個人情報ではないので出す。
"""
import csv
import glob
import os
import re
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _privacy import mask as mask_value   # noqa: E402

REAL_DIR = "data/real"
OUT_PATH = os.path.join(REAL_DIR, "未取込の列.txt")
SAMPLE_N = 3          # 列ごとに集める値のサンプル数
DEFAULT_MIN_PCT = 10  # 画面に出す入力率の下限(%)

# 移行の主戦場になるテーブル。既定ではここだけ見る(--all で全部)
# (2026-08-06 更新: import_csv.py が実際に読むテーブル名に合わせた。
#  旧一覧の d_uriage / d_urikake は実データに存在しない名前だった)
MAIN_TABLES = ["d_item", "d_siire", "d_user", "d_hanbai", "d_shohosen",
               "d_kakeuri", "d_kakeurihistory", "d_nyukin", "d_point", "d_pointhistory"]

# ── トキワが取り込み済みと【確認できている】列 ──
# ★ここに無い＝不要ではなく「未確認」。確認できたらここに足していくこと。
# ★★2026-08-06 全面書き直し: scripts/import_csv.py が実際に r.get() で読んでいる列と
#   1つずつ突き合わせた。以前の一覧は実装と食い違っており(strcbuncode→実際はstrdbuncode、
#   strsecode→実際はstriscode)、さらに「strtaghinname=取込済み」「d_siire=取込済み」と
#   書いてあったが**どちらも取込は実装されていない**(列だけ作って取込を入れ忘れていた)。
#   この一覧を直す時は、必ず import_csv.py の該当行と突き合わせること。
KNOWN = {
    "d_item": {
        "lngsykey": "product_key(商品キー。strsytencodeと組で使用)",
        "strsytencode": "product_key(商品キーの店舗部分)",
        "strsyno": "product_no(商品番号)",
        "strsyname": "name(商品名)",
        "strsyinfo": "info(商品情報)",
        "strdbuncode": "category(大分類。m_dbunruiで名前解決)",
        "strbrcode": "brand(ブランド。m_brandで名前解決)",
        "strbrandcode": "brand(別名も見る)", "strbrand": "brand(別名も見る)",
        "strjicode": "metal(地金。m_jiganeで名前解決)",
        "strjiganecode": "metal(別名も見る)", "strjigane": "metal(別名も見る)",
        "strsirsakicode": "supplier(仕入先。m_siiresakiで名前解決)",
        "curorokin": "cost_price(仕入単価/下代)",
        "curkoukin": "list_price(上代)",
        "strjotaikbn": "state(状態区分)",
        "strhotencode": "location(保管場所)",
        "striscode": "center_stone(中石。m_ishiで名前解決)",
        "curmainjuryo": "center_carat(中石重量)",
        "strcolcode": "color", "strclacode": "clarity", "strcutcode": "cut",
        "strkanbno": "cert_no(鑑別書No)",
        "strpicfilename": "image_file(商品写真)",
        "dattoudate": "registered_at(登録日)",
        # ★strtaghinname(タグ品名)は products.tag_name 列だけ作って取込が未実装。
        #   ここに書かない=未確認として表示されるのが正しい(2026-08-06 判明)。
    },
    # ★d_siire は取込が一切実装されていない(2026-08-06 判明)。
    #   products.maker_no(品番=strsirsycode)の列だけ作って取込を入れ忘れている。
    #   値札はこの品番を刷るため、8月末の再取込までに実装が必要。
    #   → 全列が「未確認」と表示されるのが正しい状態。取込を実装したらここに足すこと。
    "d_siire": {},
    "d_user": {
        "lngkokey": "customer_id(strkotencodeと組で使用)",
        "strkotencode": "customer_id(店舗部分)・store_code",
        "strkoname": "name", "strkokana": "kana", "strkotel": "tel", "strtel2": "tel2",
        "strkopos": "postal", "strkojyu1": "address", "strkojyu2": "address2",
        "strsexkbn": "gender(1=女,2=男)",
        "datbirthday": "birthday", "datwedddate": "wedding_day",
        "strrank": "rank",
        "strtikucode": "district(m_tikuで名前解決)",
        "strtiku": "district(別名も見る)", "strchikucode": "district(別名も見る)",
        "strdmkbn": "dm_ok(1=送る,2=送らない)",
        "strpcmail": "email", "strkeitaimail": "email(PCメールが空の時)",
        "lngfinsize1": "ring_size(指1リングサイズ)",
        "strpiasukbn": "pierce(1=有,2=無)",
        "strtancode": "staff_code・staff_name",
        "strkanritenpo": "store_code(管理店舗)",
        "dattoudate": "registered_at",
    },
    "d_user_memo": {
        "lngkokey": "customer_id", "strkotencode": "customer_id(店舗部分)",
        "datinpdate": "updated_at",
        **{f"strmemo{i:02d}": "customer_memos.body" for i in range(1, 11)},
    },
    "d_famiry": {
        "lngkokey": "customer_id", "strkotencode": "customer_id(店舗部分)",
        "strfamiryname": "name", "strzokukbn": "relation(続柄)",
        "strsexkbn": "gender", "datbirthday": "birthday",
    },
    "d_hanbai": {
        "lngkokey": "customer_id", "strkotencode": "customer_id(店舗部分)・store_code",
        "lngsykey": "product_key", "strsytencode": "product_key(店舗部分)",
        "curdenpyono": "slip_no(伝票番号=明細のグループ化)",
        "datkaidate": "sold_at", "datcredate": "sold_at(買上日が空の時)",
        "strhantancode": "staff_code・staff_name(m_tantouで名前解決)",
        "strkakekbn": "pay_method(1=現金,2=掛売,3=クレジット…)",
        "strcrekbn": "credit_kind(JCB/VISA等)",
        "strdocode": "motive(動機。m_doukiで名前解決)",
        "strbacode": "place(購入場所。m_basyoで名前解決)",
        "curusepoint": "used_points", "curkasanpoint": "earned_points",
        "strkokname": "free_name(商品台帳に無い明細の品名)",
        "strsyinfo": "info",
        "curteika": "list_price", "curkaikin": "amount", "curkaizeikin": "tax",
        "curwariritu": "discount_rate",
    },
    "d_kakeuri": {
        "lngkokey": "customer_id", "strkotencode": "customer_id(店舗部分)",
        "lngsykey": "product_key", "strsytencode": "product_key(店舗部分)",
        "datkaidate": "bought_at", "curatamakin": "down_payment",
        "curzankin": "balance", "datnyukindate": "last_paid_at",
    },
    "d_kakeurihistory": {
        "lngkokey": "customer_id", "strkotencode": "customer_id(店舗部分)",
        "lngkakekbn": "entry_type", "datkakedate": "entry_date",
        "curkakekin": "amount", "curnyukin": "paid", "strbiko": "note",
    },
    "d_nyukin": {
        "lngkokey": "customer_id", "strkotencode": "customer_id(店舗部分)",
        "datnyudate": "entry_date", "curnyukin": "paid", "strbiko": "note",
    },
    "d_point": {
        "lngkokey": "customer_id", "strkotencode": "customer_id(店舗部分)",
        "curpointzan": "point_balances.balance", "datkoshinbi": "updated_at",
    },
    "d_pointhistory": {
        "lngkokey": "customer_id", "strkotencode": "customer_id(店舗部分)",
        "lngpointkbn": "tx_type", "curkasanpoint": "add_points", "curusepoint": "use_points",
        "curzanpoint": "balance(取引後残高)", "strsyname": "product_name",
        "dathakko": "occurred_at", "datinpdate": "occurred_at(発行日が空の時)",
        "lngpointseq": "残高補完の最終行判定",
    },
    "d_shohosen": {
        "lngkokey": "customer_id", "strkotencode": "customer_id(店舗部分)",
        "lngshohosenno": "rx_no", "stryotokbn": "purpose(1=常用,2=遠用,3=近用)",
        "lngsykey1": "lens_key", "strsytencode1": "lens_key(店舗部分)",
        "lngsykey2": "frame_key", "strsytencode2": "frame_key(店舗部分)",
        "strsph_r": "sph_r", "strsph_l": "sph_l", "strcyl_r": "cyl_r", "strcyl_l": "cyl_l",
        "strax_r": "ax_r", "strax_l": "ax_l", "stradd_r": "add_r", "stradd_l": "add_l",
        "strpr_r": "pri_r", "strpr_l": "pri_l", "strbase_r": "base_r", "strbase_l": "base_l",
        "strpden_r": "pd_far_r", "strpden_l": "pd_far_l", "strpden_b": "pd_far_both",
        "strpdkin_r": "pd_near_r", "strpdkin_l": "pd_near_l", "strpdkin_b": "pd_near_both",
        "strragan_r": "naked_r", "strragan_l": "naked_l", "strragan_b": "naked_both",
        "strkyosei_r": "corrected_r", "strkyosei_l": "corrected_l", "strkyosei_b": "corrected_both",
        "curgokeiteika": "total_list", "curgokeiurine": "total_sell",
        "strtaioshacode": "handler(m_tantouで名前解決)", "datinpdate": "rx_date",
    },
    "d_systemuser": {
        "struserid": "app_users.user_id", "lngmasterflg": "role(管理者判定)",
        "strsytencode": "store_code", "strdispname": "display_name",
    },
}


def norm_type(v):
    """値の形をざっくり分類する(何の項目か推測しやすくするため)。"""
    s = str(v).strip()
    # 月1-12・日1-31まで見る。緩く書くと電話番号(0561-32-3736)を日付と誤判定するため
    if re.fullmatch(r"\d{4}[/-](0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])([ T].*)?", s):
        return "日付"
    if re.fullmatch(r"-?[\d,]+", s):
        return "数字"
    if re.fullmatch(r"-?[\d,]*\.\d+", s):
        return "小数"
    if re.fullmatch(r"[ｦ-ﾟ\s]+", s):
        return "半角カナ"
    if re.fullmatch(r"[A-Za-z0-9\-_/\.\s]+", s):
        return "英数記号"
    return "文字"


def read_header_and_rows(path):
    """CSVの見出しと行を返す。宝飾ナビの書き出しは cp932 が多いので順に試す。
    大きい表(20万行)があるので、全行をメモリに載せず1行ずつ流す。"""
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            f = open(path, "r", encoding=enc, newline="")
            rd = csv.reader(f)
            head = next(rd)
            return f, rd, head
        except UnicodeDecodeError:
            f.close()
            continue
        except StopIteration:
            f.close()
            return None, None, None
    return None, None, None


def scan_table(path):
    """1テーブルを走査して、列ごとに (非空件数, 総行数, サンプル, 形) を返す。"""
    f, rd, head = read_header_and_rows(path)
    if not head:
        return None, None, 0
    stats = OrderedDict((c, {"n": 0, "samples": [], "types": {}}) for c in head)
    total = 0
    try:
        for row in rd:
            total += 1
            for col, val in zip(head, row):
                s = "" if val is None else str(val).strip()
                if not s:
                    continue
                st = stats[col]
                st["n"] += 1
                t = norm_type(s)
                st["types"][t] = st["types"].get(t, 0) + 1
                if len(st["samples"]) < SAMPLE_N and s not in st["samples"]:
                    st["samples"].append(s)
    finally:
        f.close()
    return head, stats, total


def table_name(path):
    return os.path.splitext(os.path.basename(path))[0]


def main():
    argv = sys.argv[1:]
    show_all = "--all" in argv
    min_pct = DEFAULT_MIN_PCT
    if "--min" in argv:
        try:
            min_pct = float(argv[argv.index("--min") + 1])
        except (IndexError, ValueError):
            print("[エラー] --min のあとに数字を入れてください(例: --min 30)")
            sys.exit(1)
    only = [a for a in argv if not a.startswith("--") and not a.replace(".", "").isdigit()]

    csv_dir = os.path.join(REAL_DIR, "csv")
    if not os.path.isdir(csv_dir):
        csv_dir = REAL_DIR
    files = sorted(glob.glob(os.path.join(csv_dir, "*.csv")))
    if not files:
        print(f"[エラー] {csv_dir} に csv がありません。実データのあるPCで実行してください。")
        sys.exit(1)

    if only:
        files = [p for p in files if table_name(p) in only]
    elif not show_all:
        files = [p for p in files if table_name(p) in MAIN_TABLES]
    if not files:
        print("[エラー] 対象のテーブルが見つかりません。--all で全テーブルを見られます。")
        sys.exit(1)

    print("=" * 72)
    print("  宝飾ナビの列のうち、値が入っているのにトキワへ取り込んでいないもの")
    print(f"  対象テーブル: {len(files)} 件 / 画面表示は入力率 {min_pct}% 以上")
    print("  ※「未確認」は不要という意味ではありません。対応を確認できていない列です")
    print("=" * 72)

    report = []
    for path in files:
        tname = table_name(path)
        head, stats, total = scan_table(path)
        if not head:
            print(f"\n[読めません] {tname}")
            continue
        known = KNOWN.get(tname, {})
        rows = []
        for col in head:
            st = stats[col]
            pct = (st["n"] / total * 100) if total else 0.0
            top = max(st["types"].items(), key=lambda kv: kv[1])[0] if st["types"] else "-"
            samples = [mask_value(col, v, 24) or "" for v in st["samples"]]
            rows.append({"col": col, "pct": pct, "n": st["n"], "type": top,
                         "samples": samples, "known": known.get(col)})
        rows.sort(key=lambda r: -r["pct"])
        report.append((tname, total, rows))

        unknown = [r for r in rows if not r["known"] and r["pct"] >= min_pct]
        print(f"\n■ {tname}  ({total:,}行 / 全{len(head)}列 / "
              f"取込済み{len([r for r in rows if r['known']])}列)")
        if not unknown:
            print("   入力率の高い未確認の列はありません。")
            continue
        print(f"   未確認で入力率{min_pct}%以上の列: {len(unknown)} 件")
        print(f"   {'列名':<24}{'入力率':>7}  {'形':<6} 値の例")
        for r in unknown:
            ex = " / ".join(s for s in r["samples"] if s)
            print(f"   {r['col']:<24}{r['pct']:>6.1f}%  {r['type']:<6} {ex[:46]}")

    # 全列ぶんはファイルへ(画面が流れてしまうため)
    try:
        os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            f.write("宝飾ナビの列の棚卸し(全列)。入力率の高い順。\n")
            f.write("印: [済]=トキワへの取込を確認済み / [未]=未確認(不要という意味ではない)\n\n")
            for tname, total, rows in report:
                f.write(f"■ {tname}  ({total:,}行 / {len(rows)}列)\n")
                for r in rows:
                    tag = "[済]" if r["known"] else "[未]"
                    note = f"  → {r['known']}" if r["known"] else ""
                    ex = " / ".join(s for s in r["samples"] if s)
                    f.write(f"  {tag} {r['col']:<24}{r['pct']:>6.1f}%  "
                            f"{r['type']:<6} {ex[:60]}{note}\n")
                f.write("\n")
        print(f"\n全列ぶんの一覧を {OUT_PATH} に書き出しました(GitHubには載りません)。")
    except OSError as e:
        print(f"\n[注意] 一覧ファイルを書けませんでした: {e}")

    print("\n" + "=" * 72)
    print("  入力率の高い未確認の列から順に、何の項目かを見ていくのが効率的です。")
    print("  中身を確かめたい列があれば、その値で find_column.py を実行してください:")
    print("    python3 scripts/find_column.py <商品番号など> <調べたい値>")
    print("=" * 72)


if __name__ == "__main__":
    main()
