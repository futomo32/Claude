# -*- coding: utf-8 -*-
"""紙の売掛台帳を Excel に打ち込んで、まとめてトキワに取り込む道具。

正式運用の開始時、紙で管理していた売掛(未回収残高)を1件ずつ画面から入力すると
時間がかかるため、Excel に打ち込んだものをまとめて登録できるようにしたもの。

  python3 scripts/import_receivables.py --template   # 入力用ファイルを作る
  python3 scripts/import_receivables.py              # 下読み(取り込まない)★まずこれ
  python3 scripts/import_receivables.py --commit     # 実際に取り込む

★既定は「下読み」です。--commit を付けるまで DB は一切変更しません。
★--commit の前に db/tokiwa.db のバックアップを自動で取ります。

【この道具が守っていること】
1. **顧客が1人に決まらない行は取り込みません。**同姓同名に付けてしまうと、
   誰の売掛か分からなくなり、取り立て漏れや二重請求になるため。
   決まらなかった行は理由を付けて data/real/売掛_要確認.csv に出します。
2. **合計金額を必ず表示します。**紙の合計と1円単位で突き合わせるため。
3. **二重取り込みを警告します。**同じ顧客・同じ金額・同じ日付が、ファイルの中や
   DBに既にある場合に知らせます(同じファイルを2回流す事故を防ぐ)。

※この画面には顧客名が表示されます(店内で使う道具のため)。ログには残しません。
"""
import csv
import datetime
import os
import re
import shutil
import sqlite3
import sys
import unicodedata

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")
REAL = os.path.join(BASE, "data", "real")
DEFAULT_CSV = os.path.join(REAL, "売掛入力.csv")
DEFAULT_XLSX = os.path.join(REAL, "売掛入力.xlsx")
NG_OUT = os.path.join(REAL, "売掛_要確認.csv")

# 入力ファイルの見出し。ここに書いた名前でExcelの列を探す(順番は問わない)
COLS = ["顧客ID", "顧客名", "電話", "商品名", "買上日", "売掛残高", "備考"]

SAMPLE = [
    ["", "山田 太郎", "0565-00-0000", "ダイヤリング", "2026/6/15", "120000", "紙台帳P.3"],
    ["", "鈴木 花子", "", "ネックレス", "2026/7/2", "58000", ""],
]


# ── 文字と数字の正規化 ───────────────────────────────
def nfkc(v):
    """全角と半角をそろえる(Excelから貼ると混ざるため)。"""
    return unicodedata.normalize("NFKC", str(v or "")).strip()


def name_key(v):
    """氏名の照合用。空白・記号を落として比べる(「山田 太郎」と「山田太郎」を同じに)。"""
    t = nfkc(v)
    return re.sub(r"[\s　・.,-]", "", t)


def tel_key(v):
    """電話の照合用。数字だけにする(ハイフンの有無・全角に左右されない)。"""
    return re.sub(r"\D", "", nfkc(v))


def money(v):
    """金額を整数に。桁区切りのカンマ・円・¥・空白は無視する。
    数字にならなければ None を返す(呼び側でエラーにする)。"""
    t = nfkc(v).replace(",", "").replace("¥", "").replace("円", "").replace(" ", "")
    if not t:
        return None
    try:
        return int(float(t))
    except ValueError:
        return None


def date_str(v):
    """日付を YYYY-MM-DD に。Excelの日付セル・2026/6/15・2026-6-15・20260615 に対応。
    空欄は None(買上日が分からない紙もあるため許す)。読めなければ False を返す。"""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%Y-%m-%d")
    t = nfkc(v)
    m = re.match(r"^(\d{4})[/\-.年](\d{1,2})[/\-.月](\d{1,2})", t)
    if not m:
        m = re.match(r"^(\d{4})(\d{2})(\d{2})$", t)
    if not m:
        return False
    y, mo, d = (int(x) for x in m.groups())
    try:
        return datetime.date(y, mo, d).isoformat()
    except ValueError:
        return False


# ── 入力ファイルの読み書き ──────────────────────────
def make_template(path):
    """入力用のファイルを作る。Excelでそのまま開ける文字コード(cp932)にする。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        print(f"[中止] すでにあります: {path}")
        print("  上書きすると打ち込んだ内容が消えるため、作りません。")
        print("  作り直したい場合は、いまのファイルの名前を変えてから実行してください。")
        return False
    with open(path, "w", encoding="cp932", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for row in SAMPLE:
            w.writerow(row)
    print(f"入力用ファイルを作りました: {os.path.abspath(path)}")
    print()
    print("  ・Excelでそのまま開けます。1行目の見出しは消さないでください。")
    print("  ・2行目以降の見本は、打ち込む前に消してください。")
    print("  ・顧客IDが分かるならIDを入れるのが確実です。分からなければ顧客名(＋電話)。")
    print("  ・売掛残高は「いま残っている金額」を入れてください(頭金を引いたあとの額)。")
    print("  ・保存するときは形式を変えず『CSV』のまま上書き保存してください。")
    return True


def read_rows(path):
    """入力ファイルを読み、[(行番号, {列名: 値})] を返す。csv と xlsx の両方に対応。"""
    if path.lower().endswith((".xlsx", ".xlsm")):
        try:
            import openpyxl
        except ImportError:
            print("[エラー] xlsx を読むには openpyxl が必要です。")
            print("  python -m pip install openpyxl を実行するか、CSV形式で保存してください。")
            sys.exit(1)
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        head, out = None, []
        for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if row is None or all(c is None for c in row):
                continue
            if head is None:
                head = [nfkc(c) for c in row]
                continue
            out.append((i, {head[j]: row[j] for j in range(len(head)) if j < len(row)}))
        wb.close()
        return out
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                rd = csv.DictReader(f)
                return [(i, r) for i, r in enumerate(rd, start=2)]
        except UnicodeDecodeError:
            continue
    print(f"[エラー] 文字コードが読めません: {path}")
    sys.exit(1)


# ── 顧客の特定 ──────────────────────────────────
def build_index(con):
    """顧客を引くための索引。氏名・電話は照合用に正規化して持つ。"""
    by_id, by_name, by_name_tel = {}, {}, {}
    for cid, nm, tel, tel2 in con.execute(
            "SELECT customer_id, name, tel, tel2 FROM customers"):
        by_id[str(cid).strip()] = nm
        k = name_key(nm)
        if k:
            by_name.setdefault(k, []).append((cid, nm))
            for t in (tel, tel2):
                tk = tel_key(t)
                if tk:
                    by_name_tel.setdefault((k, tk), []).append((cid, nm))
    return by_id, by_name, by_name_tel


def resolve(row, idx):
    """1行から顧客を決める。(顧客ID, 表示名, 理由) を返す。決まらなければ顧客IDは None。

    ★決め方の順番: ①顧客ID ②顧客名＋電話 ③顧客名だけ。
      1人に決まらないものは取り込まない(同姓同名に付けてしまわないため)。
    """
    by_id, by_name, by_name_tel = idx
    cid = nfkc(row.get("顧客ID"))
    if cid:
        if cid in by_id:
            return cid, by_id[cid], ""
        return None, nfkc(row.get("顧客名")), f"顧客ID『{cid}』が見つかりません"
    nk = name_key(row.get("顧客名"))
    if not nk:
        return None, "", "顧客IDも顧客名も空です"
    tk = tel_key(row.get("電話"))
    if tk:
        hit = by_name_tel.get((nk, tk), [])
        if len(hit) == 1:
            return hit[0][0], hit[0][1], ""
        if len(hit) > 1:
            return None, nfkc(row.get("顧客名")), f"氏名と電話が同じ人が{len(hit)}人います"
    hit = by_name.get(nk, [])
    if len(hit) == 1:
        return hit[0][0], hit[0][1], ""
    if len(hit) > 1:
        return None, nfkc(row.get("顧客名")), f"同じ氏名の人が{len(hit)}人います(電話を入れると絞れます)"
    return None, nfkc(row.get("顧客名")), "その氏名の顧客が見つかりません"


def main():
    args = [a for a in sys.argv[1:]]
    do_commit = "--commit" in args
    if do_commit:
        args.remove("--commit")
    assume_yes = "--yes" in args
    if assume_yes:
        args.remove("--yes")
    if "--template" in args:
        args.remove("--template")
        make_template(args[0] if args else DEFAULT_CSV)
        return

    # 読み込むファイル(指定が無ければ xlsx → csv の順に探す)
    if args:
        path = args[0]
    elif os.path.exists(DEFAULT_XLSX):
        path = DEFAULT_XLSX
    else:
        path = DEFAULT_CSV
    if not os.path.exists(path):
        print(f"[エラー] 入力ファイルがありません: {path}")
        print("  先に  python3 scripts/import_receivables.py --template  で作ってください。")
        sys.exit(1)
    if not os.path.exists(DB):
        print(f"[エラー] DBがありません: {DB}")
        sys.exit(1)

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    idx = build_index(con)
    rows = read_rows(path)
    print(f"読み込み元: {os.path.abspath(path)}  ({len(rows)}行)\n")

    ok, ng = [], []
    seen = {}                       # ファイルの中の重複を見つける用
    for lineno, r in rows:
        r = {nfkc(k): v for k, v in r.items() if k is not None}
        # 全部空の行は読み飛ばす(Excelの下の方に空行が残ることが多いため)
        if not any(nfkc(v) for v in r.values()):
            continue
        cid, disp, why = resolve(r, idx)
        amount = money(r.get("売掛残高"))
        bought = date_str(r.get("買上日"))
        name = nfkc(r.get("商品名")) or None
        note = nfkc(r.get("備考")) or None
        if not why and amount is None:
            why = "売掛残高が数字ではありません"
        elif not why and amount <= 0:
            why = "売掛残高が0以下です"
        if not why and bought is False:
            why = "買上日が読めません(例 2026/6/15)"
        if why:
            ng.append((lineno, disp, nfkc(r.get("売掛残高")), why))
            continue
        key = (cid, amount, bought)
        dup = ""
        if key in seen:
            dup = f"ファイル内の{seen[key]}行目と同じ内容"
        else:
            seen[key] = lineno
            n = con.execute(
                "SELECT COUNT(*) FROM receivables WHERE customer_id=? AND balance=? "
                "AND COALESCE(bought_at,'')=COALESCE(?,'')", (cid, amount, bought)).fetchone()[0]
            if n:
                dup = "同じ内容がDBに既にあります"
        ok.append((lineno, cid, disp, name, bought, amount, note, dup))

    total = sum(x[5] for x in ok)
    dups = [x for x in ok if x[7]]
    no_date = [x for x in ok if not x[4]]
    print("=== 下読みの結果 ===")
    print(f"  取り込める行 : {len(ok)}件")
    print(f"  ★合計金額   : {total:,} 円   ← 紙の合計と突き合わせてください")
    print(f"  要確認の行   : {len(ng)}件")
    print(f"  重複の疑い   : {len(dups)}件")
    if no_date:
        print(f"  買上日が空欄 : {len(no_date)}件(空欄のまま登録します。今日の日付では埋めません)")
    print()

    if ng:
        print("── 要確認(この行は取り込みません)──")
        for lineno, disp, amt, why in ng[:30]:
            print(f"  {lineno:>4}行目  {disp or '(名前なし)'}  {amt or '-'}円  … {why}")
        if len(ng) > 30:
            print(f"  …他{len(ng) - 30}件")
        os.makedirs(REAL, exist_ok=True)
        with open(NG_OUT, "w", encoding="cp932", newline="", errors="replace") as f:
            w = csv.writer(f)
            w.writerow(["行番号", "顧客名", "売掛残高", "理由"])
            w.writerows(ng)
        print(f"  → 全部を書き出しました: {os.path.abspath(NG_OUT)}")
        print()

    if dups:
        print("── 重複の疑い(取り込みはします。意図しているか確認してください)──")
        for lineno, _cid, disp, _nm, _bt, amt, _note, why in dups[:20]:
            print(f"  {lineno:>4}行目  {disp}  {amt:,}円  … {why}")
        if len(dups) > 20:
            print(f"  …他{len(dups) - 20}件")
        print()

    if not do_commit:
        print("※ここまでは下読みです。DBは変更していません。")
        print("  この内容でよければ  --commit  を付けて実行してください。")
        con.close()
        return
    if not ok:
        print("取り込める行がありません。中止します。")
        con.close()
        return

    if not assume_yes:
        ans = input(f"{len(ok)}件・合計 {total:,} 円 を取り込みます。よろしいですか? (yes/no): ")
        if ans.strip().lower() not in ("y", "yes"):
            print("中止しました。")
            con.close()
            return

    con.close()
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = DB + f".bak_{stamp}"
    shutil.copy2(DB, backup)
    print(f"バックアップを作成: {os.path.abspath(backup)}")

    con = sqlite3.connect(DB)
    cur = con.cursor()
    # 途中で落ちても中途半端に入らないよう、全件をひとまとまりで書く
    cur.execute("BEGIN IMMEDIATE")
    for _lineno, cid, _disp, name, bought, amount, note, _dup in ok:
        # ★買上日が空欄なら空欄のまま入れる(今日の日付で埋めない)。
        #   紙に日付が無いものを「今日買った」ことにすると経過月も日報もおかしくなるし、
        #   同じファイルを2回流したときに重複として気づけなくなるため。
        cur.execute("""INSERT INTO receivables(customer_id,product_name,bought_at,
                       down_payment,balance,last_paid_at) VALUES (?,?,?,?,?,?)""",
                    (cid, name, bought, 0, amount, None))
        cur.execute("""INSERT INTO receivable_entries(customer_id,entry_type,entry_date,
                       product_name,amount,paid,note) VALUES (?,?,?,?,?,?,?)""",
                    (cid, "掛売", bought, name, amount, None, note))
    con.commit()
    n_all = con.execute("SELECT COUNT(*) FROM receivables").fetchone()[0]
    s_all = con.execute("SELECT COALESCE(SUM(balance),0) FROM receivables").fetchone()[0]
    con.close()
    print(f"\n取り込みました: {len(ok)}件 / {total:,} 円")
    print(f"取り込み後の売掛全体: {n_all}件 / {s_all:,} 円")
    if ng:
        print(f"※要確認の {len(ng)}件は取り込んでいません。{os.path.basename(NG_OUT)} を直して"
              "もう一度流してください(取り込み済みの行は重複として知らせます)。")


if __name__ == "__main__":
    main()
