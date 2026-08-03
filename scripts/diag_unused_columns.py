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
MAIN_TABLES = ["d_item", "d_user", "d_hanbai", "d_siire", "d_uriage", "d_shohosen", "d_urikake"]

# ── トキワが取り込み済みと【確認できている】列 ──
# ★ここに無い＝不要ではなく「未確認」。確認できたらここに足していくこと。
#   (2026-08-03 時点。scripts/import_to_sqlite.py と db/schema.sql を突き合わせた結果)
KNOWN = {
    "d_item": {
        "lngsykey": "product_key(商品キー)",
        "strsyno": "product_no(商品番号)",
        "strsyname": "name(商品名)",
        "strsyinfo": "info(商品情報)",
        "strcbuncode": "category(大分類)",
        "strsirsakicode": "supplier(仕入先)",
        "curorokin": "cost_price(仕入単価/下代)",
        "curkoukin": "list_price(上代)",
        "strjotaikbn": "state(状態区分)",
        "strhotencode": "location(保管場所)",
        "strsecode": "center_stone(中石)",
        "curmainjuryo": "center_carat(中石重量)",
        "strpicfilename": "image_file(商品写真)",
        "dattoudate": "registered_at(登録日)",
        "strtaghinname": "tag_name(タグ品名) ※2026-08-03 追加",
    },
    "d_siire": {
        "lngsykey": "products と紐づけ",
        "strsirsycode": "maker_no(品番) ※2026-08-03 追加",
        "cursirtanka": "cost_price(仕入単価)",
        "dattoudate": "registered_at(登録日)",
    },
    "d_user": {
        "lngkokey": "customer_id",
        "strkoname": "name", "strkokana": "kana", "strkotel": "tel", "strtel2": "tel2",
        "strkopos": "postal", "strkojyu1": "address", "strkojyu2": "address2",
        "datbirthday": "birthday", "strtancode": "staff", "strtikucode": "district",
        "strrank": "rank", "dattoudate": "registered_at",
    },
    "d_hanbai": {
        "lngkokey": "customer_id", "lngsykey": "product_key",
        "datkaidate": "sold_at", "curkaikin": "amount", "curteika": "list_price",
        "curwariritu": "discount_rate", "strhantancode": "staff",
        "curdenpyono": "slip_id", "strdocode": "動機", "strbacode": "購入場所",
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
