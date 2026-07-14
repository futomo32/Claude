# -*- coding: utf-8 -*-
"""移行後の「紐づいていないデータ」を洗い出すレポート(読み取り専用)。

CSVソース(data/real/csv)を突き合わせ、以下を一覧化する:
  1. 担当者コード … 使われているのに担当者マスタ(m_tantou)に無い / マスタにあるが未使用
  2. 店舗コード   … 顧客・商品で使われているのに店舗マスタ(m_stor)に無い
  3. 孤児顧客     … 販売/ポイント/売掛/処方箋等が参照するが顧客台帳に無い顧客
                    → 削除済み顧客台帳(d_user_delinfo)と照合し「退会済み」か「原因不明」か判定
  4. 孤児商品     … 販売等が参照するが商品台帳に無い商品

出力: data/real/紐づけ確認レポート.md (gitignore下・PC内のみ)
実行:  python3 scripts/orphan_report.py            # data/real/csv
       python3 scripts/orphan_report.py --demo     # data/demo_csv
"""
import csv
import glob
import os
import sys
from collections import defaultdict, Counter

csv.field_size_limit(10 * 1024 * 1024)

BASE = os.path.join(os.path.dirname(__file__), "..")
SRC = os.path.join(BASE, "data", "real", "csv")


def s(v):
    if v is None:
        return None
    t = str(v).strip()
    return t or None


def rows(name):
    path = os.path.join(SRC, name + ".csv")
    if not os.path.exists(path):
        return
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            f = open(path, "r", encoding=enc, newline="")
            f.readline(); f.seek(0)
            break
        except UnicodeDecodeError:
            f.close()
    else:
        f = open(path, "r", encoding="cp932", errors="replace", newline="")
    try:
        for r in csv.DictReader(f):
            yield r
    finally:
        f.close()


def ck(r, tc="strkotencode", kc="lngkokey"):
    t, k = s(r.get(tc)), s(r.get(kc))
    return f"{t}-{k}" if t and k else None


def sample(items, n=20):
    items = list(items)
    out = "\n".join(f"    - {x}" for x in items[:n])
    if len(items) > n:
        out += f"\n    - …他 {len(items) - n:,} 件"
    return out or "    (なし)"


def main():
    global SRC
    if "--demo" in sys.argv:
        SRC = os.path.join(BASE, "data", "demo_csv")
    if not os.path.isdir(SRC):
        print(f"[エラー] フォルダが見つかりません: {SRC}")
        sys.exit(1)

    print("読み込み中…(数十秒かかる場合があります)")
    # マスタ
    cust = set(ck(r) for r in rows("d_user"))
    cust.discard(None)
    prod = set(ck(r, "strsytencode", "lngsykey") for r in rows("d_item"))
    prod.discard(None)
    staff_master = {s(r.get("strtancode")): s(r.get("strtanname")) for r in rows("m_tantou") if s(r.get("strtancode"))}
    store_master = {s(r.get("strtencode")): s(r.get("strtenname")) for r in rows("m_stor") if s(r.get("strtencode"))}
    # 削除済み顧客(退会) tc-kk → (tel, kana)
    deleted = {}
    for r in rows("d_user_delinfo"):
        k = ck(r)
        if k:
            deleted[k] = (s(r.get("strkotel")), s(r.get("strkokana")))

    out = []
    w = out.append
    w("# 紐づけ確認レポート(移行後の迷子データ)")
    w("")
    w(f"- 顧客台帳: {len(cust):,} / 商品台帳: {len(prod):,} / 担当者マスタ: {len(staff_master):,} / "
      f"店舗マスタ: {len(store_master):,} / 削除済み顧客: {len(deleted):,}")
    w("")

    # ── 1. 担当者 ─────────────────────────────
    w("## 1. 担当者コードの紐づけ")
    w("")
    used_tan = Counter()
    for name, tanfields in [("d_user", ["strtancode"]),
                            ("d_hanbai", ["strhantancode"]),
                            ("d_shohosen", ["strtaioshacode", "strshokaishacode"])]:
        for r in rows(name):
            for fld in tanfields:
                c = s(r.get(fld))
                if c:
                    used_tan[c] += 1
    unknown_tan = {c: cnt for c, cnt in used_tan.items() if c not in staff_master}
    unused_tan = {c: nm for c, nm in staff_master.items() if c not in used_tan}
    w(f"### (A) 使われているのにマスタに無い担当者コード: **{len(unknown_tan)}種**")
    w("→ 退職者や旧コードの可能性。件数付き:")
    w("")
    for c, cnt in sorted(unknown_tan.items(), key=lambda x: -x[1]):
        w(f"    - コード `{c}` … {cnt:,} 件で使用")
    if not unknown_tan:
        w("    (なし)")
    w("")
    w(f"### (B) マスタにあるが一度も使われていない担当者: **{len(unused_tan)}名**")
    w("")
    for c, nm in list(unused_tan.items())[:40]:
        w(f"    - `{c}` {nm}")
    if len(unused_tan) > 40:
        w(f"    - …他 {len(unused_tan) - 40} 名")
    if not unused_tan:
        w("    (なし)")
    w("")

    # ── 2. 店舗 ───────────────────────────────
    w("## 2. 店舗コードの紐づけ")
    w("")
    used_store = Counter()
    for r in rows("d_user"):
        c = s(r.get("strkotencode"))
        if c:
            used_store[c] += 1
    unknown_store = {c: cnt for c, cnt in used_store.items() if c not in store_master}
    w("顧客の店舗コード別件数(マスタ有無):")
    w("")
    w("| 店舗コード | 顧客数 | マスタ名 |")
    w("|---|--:|---|")
    for c, cnt in sorted(used_store.items(), key=lambda x: -x[1]):
        w(f"| {c} | {cnt:,} | {store_master.get(c, '★マスタに無し')} |")
    w("")

    # ── 3. 孤児顧客(子データが参照するが顧客台帳に無い) ──
    w("## 3. 孤児データ(参照先の顧客が台帳に無い)")
    w("")
    w("| 台帳 | 総行数 | 孤児行数 | 孤児のうち退会済み | 原因不明 |")
    w("|---|--:|--:|--:|--:|")
    all_orphan_keys = set()
    orphan_detail = {}
    for name, label in [("d_hanbai", "販売"), ("d_pointhistory", "ポイント履歴"),
                        ("d_point", "ポイント台帳"), ("d_kakeuri", "売掛台帳"),
                        ("d_kakeurihistory", "売掛履歴"), ("d_shohosen", "処方箋"),
                        ("d_famiry", "家族"), ("d_service", "サービスP")]:
        total = orphan = 0
        okeys = set()
        for r in rows(name):
            k = ck(r)
            if not k:
                continue
            total += 1
            if k not in cust:
                orphan += 1
                okeys.add(k)
        if total == 0:
            continue
        retired = sum(1 for k in okeys if k in deleted)
        unknown = len(okeys) - retired
        all_orphan_keys |= okeys
        orphan_detail[label] = okeys
        w(f"| {label} | {total:,} | {orphan:,} | {retired:,} | {unknown:,} |")
    w("")
    w(f"### 孤児になっている顧客(ユニーク): {len(all_orphan_keys):,} 名")
    retired_keys = sorted(k for k in all_orphan_keys if k in deleted)
    unknown_keys = sorted(k for k in all_orphan_keys if k not in deleted)
    w(f"- うち **退会済み(削除済み顧客台帳に存在)**: {len(retired_keys):,} 名 → 履歴のみ残す運用が安全")
    w(f"- うち **原因不明(削除記録も無い)**: {len(unknown_keys):,} 名 → 要確認")
    w("")
    w("**原因不明な顧客キーの例(店-ID):**")
    w(sample(unknown_keys, 30))
    w("")

    # ── 4. 孤児商品 ───────────────────────────
    w("## 4. 孤児商品(販売が参照するが商品台帳に無い)")
    w("")
    total = orphan = 0
    okeys = set()
    for r in rows("d_hanbai"):
        k = ck(r, "strsytencode", "lngsykey")
        if not k:
            continue
        total += 1
        if k not in prod:
            orphan += 1
            okeys.add(k)
    w(f"- 販売明細 {total:,} 行中、商品台帳に無い商品を参照: **{orphan:,} 行**({len(okeys):,} 商品キー)")
    w("- ※品名は販売台帳側に残るため表示上の実害は小。廃番・削除品の可能性。")
    w("")

    report = os.path.join(SRC, "..", "紐づけ確認レポート.md")
    report = os.path.normpath(report)
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    for line in out:
        print(line)
    print(f"\n\nレポートを書き出しました: {report}")


if __name__ == "__main__":
    main()
