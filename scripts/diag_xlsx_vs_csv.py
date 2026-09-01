# -*- coding: utf-8 -*-
"""11台帳(xlsx)の列が、CSV側にも存在するかを**値で**突き合わせる診断(2026-09-01 追加)。

【何のための道具か】
トキワの取込元は CSV(114テーブル)で、xlsx(11台帳)は使っていない。
「CSVの方が情報量が多いはず」という前提で進めてきたが、**実測はしていなかった。**
xlsx にしか無い情報があれば、それは**移行の取りこぼし**になる。それを探す。

【なぜ列名で比べないのか】
xlsx は加工済みで、`大分類名` のようにCSV側では別のマスタ(m_dbunrui)に入っている
列が大量にある。列名だけで比べると「無い」が何十件も出て、本物の漏れが埋もれる。
そこで**値そのもの**を突き合わせる: xlsx の各列から実際の値を拾い、
CSV114テーブルの全列を1回走査して、その値がどこかに入っているかを見る。

  python3 scripts/diag_xlsx_vs_csv.py            # data/real を見る
  python3 scripts/diag_xlsx_vs_csv.py --demo     # data/demo で動作確認

【読み方 — 3つに分かれます】
  ○ 対応あり     … CSV側に同じ値が見つかった。取りこぼしの心配なし
  ─ 判定できない … xlsxのその列が空っぽで、照合する値が無い
  ★ 見つからない … ここが**漏れの候補**。ただし『経過月』のような
                    計算で作った列はCSVに無くて当然なので、中身を見て仕分ける

【限界(正直に書いておく)】
・値で照合するので、CSVが持っていても**書き方が違う**と見つけられないことがある
  (和暦/西暦、コードと名前、丸め方の違いなど)。★は「漏れ確定」ではなく「要確認」。
・**2つの列を繋げて作った列は必ず★に出る。**例: 商品キー `01-104714` は
  CSV では店コードと商品IDの2列に分かれているため、そのままの値では見つからない。
  これは取りこぼしではない(トキワも同じように繋いで作っている)。
・逆に、たまたま別の表の関係ない列と値が一致して○になることもある(短い値ほど起きる)。
  そのため、数字1桁のような弱い値はそもそも照合に使わない。
・**`--demo` は動作確認にしかならない。**デモのxlsxとデモのCSVは別々に作った
  無関係なデータなので、ほぼ全部★になる。中身の判断に使わないこと。

出力するのは**列名と件数だけ**。値は出さない(個人情報を画面に出さないため)。
"""
import csv
import datetime
import glob
import os
import re
import sys
import unicodedata
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import csv_dir, xlsx_dir   # noqa: E402

csv.field_size_limit(10 * 1024 * 1024)

SAMPLE_ROWS = 800      # xlsxの先頭何行から値を拾うか
SAMPLES_PER_COL = 12   # 1列あたり何個の値で照合するか
HIT_ENOUGH = 2         # 何個当たれば「対応あり」と見なすか(1個だと偶然が混ざる)


def norm(v):
    """xlsxとCSVで書き方が違っても比べられるように、値を同じ形にそろえる。

    ・全角/半角、前後の空白 → そろえる
    ・数字 12345.00 → 12345、桁区切りのカンマ → 取る
    ・日付(Excelの日付セル / 2003/01/24 / 2003-01-24 0:00:00)→ 20030124
    """
    if v is None:
        return ""
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%Y%m%d")
    t = unicodedata.normalize("NFKC", str(v)).strip()
    if not t:
        return ""
    m = re.match(r"^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})(?:[ T].*)?$", t)
    if m:
        return f"{int(m.group(1)):04d}{int(m.group(2)):02d}{int(m.group(3)):02d}"
    c = t.replace(",", "")
    if re.match(r"^-?\d+(\.\d+)?$", c):
        f = float(c)
        return str(int(f)) if f == int(f) else str(f)
    return t


def usable(t):
    """照合に使ってよい値か。短いもの・ありふれたものは偶然当たるので使わない。"""
    if len(t) < 3:
        return False
    if re.match(r"^-?\d{1,2}$", t):     # 1〜2桁の数字(区分コード等)は弱い
        return False
    if t in ("0", "0.0", "00", "000", "本店", "なし"):
        return False
    return True


def xlsx_columns(path):
    """1つの台帳から [(列名, [照合に使う値, ...])] を返す。"""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    ws.reset_dimensions()
    head, samples = None, None
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if row is None or all(c is None for c in row):
            continue
        if head is None:
            head = [unicodedata.normalize("NFKC", str(c)).strip() if c is not None else ""
                    for c in row]
            samples = [[] for _ in head]
            continue
        for j in range(min(len(head), len(row))):
            if len(samples[j]) >= SAMPLES_PER_COL:
                continue
            t = norm(row[j])
            if usable(t) and t not in samples[j]:
                samples[j].append(t)
        if i > SAMPLE_ROWS:
            break
    wb.close()
    if head is None:
        return []
    return [(head[j], samples[j]) for j in range(len(head)) if head[j]]


def main():
    demo = "--demo" in sys.argv
    base = "data/demo" if demo else "data/real"
    xdir = xlsx_dir(base)
    cdir = csv_dir(base if not demo else "data/demo_csv")
    xfiles = sorted(glob.glob(os.path.join(xdir, "*.xlsx")))
    cfiles = sorted(glob.glob(os.path.join(cdir, "*.csv")))
    if not xfiles:
        print(f"[エラー] xlsx がありません: {xdir}")
        sys.exit(1)
    if not cfiles:
        print(f"[エラー] csv がありません: {cdir}")
        sys.exit(1)
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("[エラー] openpyxl が必要です。 python -m pip install openpyxl")
        sys.exit(1)

    print(f"台帳(xlsx): {xdir}  {len(xfiles)}ファイル")
    print(f"生ダンプ(csv): {cdir}  {len(cfiles)}ファイル\n")
    if demo:
        print("※注意: デモのxlsxとデモのCSVは別々に作った無関係なデータです。")
        print("  ほぼ全部★になりますが、それが正常です。動作の確認にだけ使ってください。\n")

    # ── ① xlsx から「探す値」を集める ──
    ledgers = {}                     # 台帳名 → [(列名, [値,...]), ...]
    wanted = defaultdict(set)        # 値 → {(台帳名, 列名), ...}
    for p in xfiles:
        nm = os.path.basename(p).split("-")[0]
        cols = xlsx_columns(p)
        ledgers[nm] = cols
        for col, vals in cols:
            for v in vals:
                wanted[v].add((nm, col))
    print(f"照合に使う値: {len(wanted):,} 種類"
          f"(全{sum(len(c) for c in ledgers.values()):,}列から抽出)\n")

    # ── ② CSVを1回だけ走査して、その値がどこにあるか探す ──
    # 実データは114テーブル・数十万行になるので、止まって見えないよう途中経過を出す
    print("CSVを走査中(114テーブルあると数分かかります)…")
    found = defaultdict(lambda: defaultdict(int))   # (台帳,列) → {CSVの列: 当たった数}
    for n_file, p in enumerate(cfiles, start=1):
        tbl = os.path.splitext(os.path.basename(p))[0]
        print(f"  [{n_file}/{len(cfiles)}] {tbl}", flush=True)
        try:
            for enc in ("utf-8-sig", "cp932", "utf-8"):
                try:
                    f = open(p, "r", encoding=enc, newline="")
                    f.readline(); f.seek(0)
                    break
                except UnicodeDecodeError:
                    f.close()
            else:
                f = open(p, "r", encoding="cp932", errors="replace", newline="")
            with f:
                rd = csv.reader(f)
                head = next(rd, [])
                for row in rd:
                    for j, cell in enumerate(row):
                        if j >= len(head):
                            break
                        t = norm(cell)
                        if t and t in wanted:
                            for key in wanted[t]:
                                found[key][f"{tbl}.{head[j]}"] += 1
        except OSError as e:
            print(f"  ※{tbl} を読めませんでした: {e}")

    # ── ③ 台帳ごとに結果を出す ──
    missing_all, empty_all = [], []
    for nm, cols in ledgers.items():
        ok, empty, miss = [], [], []
        for col, vals in cols:
            if not vals:
                empty.append(col)
                continue
            hits = found.get((nm, col), {})
            best = max(hits.values()) if hits else 0
            if best >= min(HIT_ENOUGH, len(vals)):
                ok.append(col)
            else:
                miss.append((col, len(vals), best))
        print(f"■ {nm}  ({len(cols)}列)")
        print(f"    ○ 対応あり     : {len(ok)}列")
        if empty:
            print(f"    ─ 判定できない : {len(empty)}列(その列が空でした)")
        print(f"    ★ 見つからない : {len(miss)}列")
        for col, nv, best in miss:
            print(f"        - {col}   (照合した値 {nv}個 / 最大一致 {best})")
        print()
        missing_all += [(nm, c) for c, _n, _b in miss]
        empty_all += [(nm, c) for c in empty]

    print("=" * 50)
    print(f"★ CSVに見つからなかった列: {len(missing_all)}件")
    print(f"─ 空で判定できなかった列  : {len(empty_all)}件")
    print()
    if missing_all:
        print("★の中には、取りこぼしではないものも混ざります:")
        print("  ・計算で作った列(経過月・粗利率など)… CSVに無くて当然")
        print("  ・2つの列を繋げた列(商品キーなど)  … CSVでは2列に分かれているだけ")
        print("この一覧をそのまま共有してください。中身を見て仕分けます。")
        print()
        for nm, col in missing_all:
            print(f"    {nm} / {col}")
        # ファイルにも残す(画面が流れても後から読めるように)。
        # ★書き出し先は data/real/ だけ(.gitignore 済み)。--demo では作らない——
        #   data/demo は GitHub に載るフォルダなので、そこに結果を置かない。
        if demo:
            print("\n  ※--demo では一覧ファイルを作りません(data/demo はGitHubに載るため)。")
            return
        try:
            out = os.path.join(base, "台帳の列くらべ結果.txt")
            with open(out, "w", encoding="cp932", errors="replace") as f:
                f.write("CSVに見つからなかった列(要確認)\n")
                for nm, col in missing_all:
                    f.write(f"{nm}\t{col}\n")
                f.write("\n空で判定できなかった列\n")
                for nm, col in empty_all:
                    f.write(f"{nm}\t{col}\n")
            print(f"\n  → 一覧を書き出しました: {os.path.abspath(out)}")
        except OSError as e:
            print(f"\n  ※一覧を書き出せませんでした: {e}")
    else:
        print("すべての列がCSV側にも見つかりました。取りこぼしの心配はありません。")


if __name__ == "__main__":
    main()
