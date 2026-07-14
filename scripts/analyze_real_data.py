# -*- coding: utf-8 -*-
"""宝飾ナビ 実データ分析ツール(読み取り専用・データは一切書き換えない)。

xlsx台帳一式を読み、台帳同士のつながり・孤児データ・重複・整合性を分析して
Markdownレポートを出力する。**元データは無傷**。何も削除・変更しない。

使い方(あなたのPCで):
  python scripts/analyze_real_data.py            # data/real/ を分析
  python scripts/analyze_real_data.py --demo     # data/demo/ で動作確認
  python scripts/analyze_real_data.py C:\\path\\to\\xlsxフォルダ

出力:
  <対象フォルダ>/分析レポート.md   … 人が読むレポート
  ※ data/real/ は .gitignore 済みなので、レポートもGitHubには載りません。

必要: openpyxl (pip install openpyxl)
"""
import glob
import os
import sys
from collections import defaultdict

try:
    import openpyxl
except ImportError:
    print("[エラー] openpyxl が必要です。 pip install openpyxl を実行してください。")
    sys.exit(1)

# 台帳ファイル判定(ファイル名に含まれる英字トークン。長い方を先に判定)
LEDGERS = [
    ("pointhistory", "ポイントカード履歴"),
    ("urikakehistory", "売掛履歴"),
    ("approachhistory", "アプローチ履歴"),
    ("user", "顧客台帳"),
    ("hanbai", "販売台帳"),
    ("point", "ポイント台帳"),
    ("urikake", "売掛台帳"),
    ("family", "家族台帳"),
    ("item", "商品台帳"),
    ("shohosen", "メガネ処方箋台帳"),
    ("service", "サービスポイント台帳"),
]


def detect(fn):
    base = os.path.basename(fn).lower()
    for token, label in LEDGERS:
        if token in base:
            return token, label
    return None, None


def load(fn):
    """xlsxを (header:list, rows:list[dict]) で読む。列名→値の辞書。"""
    wb = openpyxl.load_workbook(fn, read_only=True, data_only=True)
    ws = wb.active
    # 宝飾ナビのxlsxは内部の範囲情報が壊れている(A1のみと記録)ことがあり、
    # read_onlyモードだと1行しか読めない。実際のセルを走査させるためリセットする。
    ws.reset_dimensions()
    it = ws.iter_rows(values_only=True)
    header = [str(h) if h is not None else "" for h in (next(it, ()) or ())]
    rows = []
    for r in it:
        if r is None or all(c is None for c in r):
            continue
        rows.append({header[i]: r[i] for i in range(min(len(header), len(r)))})
    wb.close()
    return header, rows


def col(header, *cands):
    """ヘッダから、候補文字列を含む最初の列名を返す。"""
    for cand in cands:
        for h in header:
            if cand in h:
                return h
    return None


def s(v):
    return "" if v is None else str(v).strip()


def sample(ids, n=15):
    ids = list(ids)
    out = ", ".join(str(x) for x in ids[:n])
    if len(ids) > n:
        out += f" …他{len(ids) - n}件"
    return out or "(なし)"


def main():
    args = [a for a in sys.argv[1:]]
    target = "data/real"
    if "--demo" in args:
        target = "data/demo"
        args.remove("--demo")
    if args:
        target = args[0]

    if not os.path.isdir(target):
        print(f"[エラー] フォルダが見つかりません: {target}")
        print("  実データのxlsxを data/real/ に置いてから実行してください(--demo で動作確認)。")
        sys.exit(1)

    files = sorted(glob.glob(os.path.join(target, "*.xlsx")))
    if not files:
        print(f"[エラー] {target} に xlsx がありません。")
        sys.exit(1)

    data = {}          # token -> (header, rows)
    file_of = {}       # token -> filename
    for fn in files:
        token, label = detect(fn)
        if token and token not in data:
            data[token] = load(fn)
            file_of[token] = fn

    out = []
    w = out.append
    w("# 宝飾ナビ 実データ 分析レポート")
    w("")
    w(f"- 対象フォルダ: `{target}`")
    w(f"- 検出した台帳: {len(data)}種類 / フォルダ内xlsx {len(files)}件")
    w("- 本レポートは**読み取り専用**の分析結果です。元データは一切変更していません。")
    w("")

    # ── 1. サマリ(件数) ─────────────────────────
    w("## 1. 台帳サマリ(件数)")
    w("")
    w("| 台帳 | 件数 | 列数 |")
    w("|---|--:|--:|")
    for token, label in LEDGERS:
        if token in data:
            header, rows = data[token]
            w(f"| {label} | {len(rows):,} | {len(header)} |")
    unknown = [os.path.basename(f) for f in files if detect(f)[0] is None]
    w("")
    if unknown:
        w(f"> 種類を判定できなかったファイル: {', '.join(unknown)}")
        w("")

    # 顧客マスタのIDセット
    cust_ids = set()
    cust_header = cust_rows = None
    if "user" in data:
        cust_header, cust_rows = data["user"]
        idc = col(cust_header, "顧客id")
        cust_ids = set(s(r.get(idc)) for r in cust_rows if s(r.get(idc)))

    # 商品マスタのキーセット
    item_keys = set()
    if "item" in data:
        ih, irows = data["item"]
        kc = col(ih, "商品キー")
        item_keys = set(s(r.get(kc)) for r in irows if s(r.get(kc)))

    # ── 2. つながり(顧客IDリンク)チェック ───────────
    w("## 2. つながりチェック(顧客IDが顧客台帳に存在するか)")
    w("")
    if not cust_ids:
        w("> 顧客台帳が見つからないため判定できません。")
    else:
        w(f"顧客台帳の顧客ID: **{len(cust_ids):,}件**")
        w("")
        w("| 台帳 | 総件数 | 紐付きOK | 孤児(顧客不明) | 孤児の顧客ID例 |")
        w("|---|--:|--:|--:|---|")
        child = [("hanbai", "販売台帳"), ("point", "ポイント台帳"),
                 ("pointhistory", "ポイントカード履歴"), ("urikake", "売掛台帳"),
                 ("urikakehistory", "売掛履歴"), ("family", "家族台帳"),
                 ("shohosen", "メガネ処方箋台帳"), ("approachhistory", "アプローチ履歴"),
                 ("service", "サービスポイント台帳")]
        for token, label in child:
            if token not in data:
                continue
            h, rows = data[token]
            idc = col(h, "顧客id")
            if not idc:
                continue
            orphan_ids = set()
            ok = 0
            for r in rows:
                cid = s(r.get(idc))
                if not cid:
                    continue
                if cid in cust_ids:
                    ok += 1
                else:
                    orphan_ids.add(cid)
            orphan_rows = sum(1 for r in rows if s(r.get(idc)) and s(r.get(idc)) not in cust_ids)
            w(f"| {label} | {len(rows):,} | {ok:,} | {orphan_rows:,} | {sample(sorted(orphan_ids), 10)} |")
    w("")

    # ── 3. 商品参照チェック ───────────────────────
    w("## 3. 商品参照チェック(商品キーが商品台帳に存在するか)")
    w("")
    if not item_keys:
        w("> 商品台帳が見つからないため判定できません。")
    else:
        w(f"商品台帳の商品キー: **{len(item_keys):,}件**")
        w("")
        w("| 台帳 | 商品キーあり件数 | 存在する | 不明な商品キー |")
        w("|---|--:|--:|--:|")
        for token, label in [("hanbai", "販売台帳"), ("pointhistory", "ポイントカード履歴"),
                             ("urikakehistory", "売掛履歴"), ("urikake", "売掛台帳")]:
            if token not in data:
                continue
            h, rows = data[token]
            kc = col(h, "商品キー")
            if not kc:
                continue
            have = ok = 0
            for r in rows:
                k = s(r.get(kc))
                if not k:
                    continue
                have += 1
                if k in item_keys:
                    ok += 1
            w(f"| {label} | {have:,} | {ok:,} | {have - ok:,} |")
    w("")

    # ── 4. 顧客の重複疑い ─────────────────────────
    w("## 4. 顧客の重複疑い")
    w("")
    if cust_rows:
        namec = col(cust_header, "顧客名(フリガナ)") and col(cust_header, "顧客名")
        namec = col(cust_header, "顧客名")
        telc = col(cust_header, "顧客tel")
        idc = col(cust_header, "顧客id")
        by_tel = defaultdict(set)
        by_nametel = defaultdict(set)
        for r in cust_rows:
            cid = s(r.get(idc))
            tel = s(r.get(telc)).replace("-", "").replace(" ", "")
            name = s(r.get(namec)).replace("　", " ")
            if tel and tel not in ("0", "0000000000"):
                by_tel[tel].add(cid)
            if name and tel:
                by_nametel[(name, tel)].add(cid)
        dup_tel = {k: v for k, v in by_tel.items() if len(v) > 1}
        dup_nt = {k: v for k, v in by_nametel.items() if len(v) > 1}
        w(f"- 同じ電話番号を持つ顧客が複数: **{len(dup_tel):,}組**")
        w(f"- 同じ「氏名＋電話」の顧客が複数(重複登録の可能性大): **{len(dup_nt):,}組**")
        w("")
        if dup_nt:
            w("氏名＋電話が一致する組の顧客ID(先頭10組):")
            w("")
            for (name, tel), ids in list(dup_nt.items())[:10]:
                w(f"- 電話 {tel} / ID: {', '.join(sorted(ids))}")
            w("")
    else:
        w("> 顧客台帳が無いため判定できません。")
    w("")

    # ── 5. 欠損チェック ───────────────────────────
    w("## 5. 必須項目の欠損(顧客台帳)")
    w("")
    if cust_rows:
        namec = col(cust_header, "顧客名")
        telc = col(cust_header, "顧客tel")
        no_name = sum(1 for r in cust_rows if not s(r.get(namec)))
        no_tel = sum(1 for r in cust_rows if not s(r.get(telc)) or s(r.get(telc)) in ("0", "0000000000"))
        w(f"- 氏名が空: **{no_name:,}件**")
        w(f"- 電話が空/ダミー(0等): **{no_tel:,}件**")
    w("")

    # ── 6. ポイント整合 ───────────────────────────
    w("## 6. ポイント残高の整合(台帳の現残 vs 履歴の最終残)")
    w("")
    if "point" in data and "pointhistory" in data:
        ph, prows = data["point"]
        pid = col(ph, "顧客id")
        pbal = col(ph, "現残ポイント", "現残")
        hh, hrows = data["pointhistory"]
        hid = col(hh, "顧客id")
        hseq = col(hh, "ポイント履歴連番", "連番")
        hbal = col(hh, "残ポイント数", "残ポイント")
        last_bal = {}
        last_seq = {}
        for r in hrows:
            cid = s(r.get(hid))
            if not cid:
                continue
            try:
                seq = int(r.get(hseq) or 0)
            except (ValueError, TypeError):
                seq = 0
            if cid not in last_seq or seq >= last_seq[cid]:
                last_seq[cid] = seq
                last_bal[cid] = r.get(hbal)
        mism = 0
        checked = 0
        examples = []
        for r in prows:
            cid = s(r.get(pid))
            if not cid or cid not in last_bal:
                continue
            checked += 1
            try:
                a = int(r.get(pbal) or 0)
                b = int(last_bal[cid] or 0)
            except (ValueError, TypeError):
                continue
            if a != b:
                mism += 1
                if len(examples) < 10:
                    examples.append(f"ID {cid}: 台帳{a} / 履歴{b}")
        w(f"- 照合できた顧客: {checked:,}件")
        w(f"- 残高が一致しない顧客: **{mism:,}件**")
        if examples:
            w("")
            w("不一致の例:")
            for e in examples:
                w(f"  - {e}")
    else:
        w("> ポイント台帳またはポイント履歴が無いため判定できません。")
    w("")

    # ── 7. 処方箋の宝飾品混入 ──────────────────────
    w("## 7. メガネ処方箋の宝飾品混入チェック")
    w("")
    if "shohosen" in data:
        sh, srows = data["shohosen"]
        lens_c = col(sh, "商品名(レンズ)")
        frame_c = col(sh, "商品名(フレーム)")
        JEWEL = ("リング", "ネックレス", "ペンダント", "ピアス", "ブレス", "ダイヤ",
                 "指輪", "地金", "Pt", "K18", "18金")
        GLASS = ("レンズ", "フレーム", "メガネ", "眼鏡", "度")
        suspect = []
        for r in srows:
            txt = s(r.get(lens_c)) + " " + s(r.get(frame_c))
            if any(j in txt for j in JEWEL) and not any(g in txt for g in GLASS):
                suspect.append(txt.strip())
        w(f"- 処方箋にレンズ/フレーム以外(宝飾品らしき)商品が紐づく疑い: **{len(suspect):,}件**")
        for t in suspect[:10]:
            w(f"  - {t}")
    else:
        w("> 処方箋台帳が無いため判定できません。")
    w("")

    # ── 8. 整理の提案(自動削除はしない) ──────────────
    w("## 8. 整理の提案(※自動では何もしません。承認後に実施)")
    w("")
    w("- **孤児データ(第2章)**: 顧客が存在しない履歴。移行前に「削除」か「顧客復元」を判断。")
    w("- **重複顧客(第4章)**: 氏名＋電話一致は統合候補。どのIDを残すか決めて名寄せ。")
    w("- **不明な商品参照(第3章)**: 廃番商品の可能性。品名は履歴側に残るため実害小、要確認。")
    w("- **ポイント不一致(第6章)**: 移行時は「履歴の最終残」を正とするのが安全。")
    w("- **処方箋の宝飾混入(第7章)**: 誤登録。処方箋から切り離す。")
    w("")
    w("> 次のステップ: このレポートを共有してもらえれば、項目ごとに")
    w("> 「削除/統合/保留」の具体案を作り、承認後に整理スクリプトを用意します。")

    report = os.path.join(target, "分析レポート.md")
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("分析完了。レポートを出力しました:")
    print(f"  {report}")
    print("")
    # コンソールにも要点(件数)を表示
    for line in out:
        if line.startswith("## ") or line.startswith("- ") or line.startswith("| "):
            print(line)


if __name__ == "__main__":
    main()
