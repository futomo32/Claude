# -*- coding: utf-8 -*-
"""区分コード→名前の対応表を xlsx から自動抽出する(個人情報は出さない)。

xlsx台帳には「◯◯コード」と「◯◯(名前)」の両方の列があるため、
その組をユニークに集計すれば、CSV移行で数字のままになっている区分
(商品の状態区分・支払方法・処方箋の用途など)の正解対応表が得られる。

出力するのは【コードと名前の組・件数】のみ。顧客名などは一切出さない。

  python3 scripts/diag_kubun.py        # data/real のxlsxから抽出
"""
import glob
import os
import sys
from collections import Counter

try:
    import openpyxl
except ImportError:
    print("[エラー] openpyxl が必要です。 pip3 install openpyxl")
    sys.exit(1)

XDIR = os.path.join(os.path.dirname(__file__), "..", "data", "real")

# (ファイル判定キー, [(コード列, 名前列), ...])
TARGETS = [
    ("item", [("状態区分コード", "状態区分"), ("仕入区分コード", "仕入区分")]),
    ("hanbai", [("掛売区分/種別コード", "掛売区分/種別"),
                ("クレジット種別区分コード", "クレジット種別区分"),
                ("購入動機コード", "購入動機"), ("購入場所コード", "購入場所")]),
    ("user", [("性別コード", "性別"), ("dm送付有無コード", "dm送付有無"),
              ("住居コード", "住居"), ("ピアス穴有無コード", "ピアス穴有無"),
              ("顧客ランクコード", "顧客ランク")]),
    ("shohosen", [("用途区分", "用途名称"), ("処方区分", "処方名称")]),
]


def s(v):
    if v is None:
        return None
    t = str(v).strip()
    return t or None


def find(key):
    for p in sorted(glob.glob(os.path.join(XDIR, "*.xlsx"))):
        base = os.path.basename(p)
        if key in base:
            return p
    return None


def main():
    for key, pairs in TARGETS:
        p = find(key)
        if not p:
            print(f"[スキップ] {key} のxlsxが見つかりません")
            continue
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        ws = wb.active
        ws.reset_dimensions()
        it = ws.iter_rows(values_only=True)
        header = [str(h) if h is not None else "" for h in next(it)]
        idx = {}
        for code_col, name_col in pairs:
            ci = header.index(code_col) if code_col in header else None
            ni = header.index(name_col) if name_col in header else None
            if ci is not None and ni is not None:
                idx[(code_col, name_col)] = (ci, ni)
        counters = {k: Counter() for k in idx}
        for r in it:
            if r is None:
                continue
            for k, (ci, ni) in idx.items():
                if ci < len(r) and ni < len(r):
                    c, nm = s(r[ci]), s(r[ni])
                    if c is not None or nm is not None:
                        counters[k][(c, nm)] += 1
        wb.close()
        print(f"■ {os.path.basename(p)}")
        for (code_col, name_col), cnt in counters.items():
            print(f"  ── {code_col} ↔ {name_col} ──")
            for (c, nm), n in cnt.most_common(30):
                print(f"     コード {c!r:8} → {nm!r}  ({n:,}件)")
            if len(cnt) > 30:
                print(f"     …他 {len(cnt) - 30} 種")
        print()


if __name__ == "__main__":
    main()
