# -*- coding: utf-8 -*-
"""レシート桁数(印字幅)確定テスト。1枚で「文字が何桁まで収まるか」を決める。

背景: 現在の RECEIPT_WIDTH=28桁(336ドット)は「30桁で右端がはみ出た」実測(2026-07-29)
から決めたが、中央寄せテストの目盛りは400ドットの数字まで印字された(2026-07-30)。
実際の印字幅は384〜432ドットある可能性が高く、桁数を増やせば右余白が減って
罫線・金額・中央寄せが紙幅いっぱいにバランスする。

印字内容: 28/30/32/34/36桁それぞれについて
  ラベル行「[28桁] ↓この行が折り返さず1行なら28桁OK」
  検証行  「1234567890...=END」(ちょうどN桁。右端に END)
→ **折り返さずに END まで1行で印字された最大の桁数**を選んで伝えてもらう。
  その値を server/devices.py の RECEIPT_WIDTH に反映する(PAPER_DOTS=桁数×12も同時に)。

  python3 hardware/width_test.py

注意: 宝飾ナビ起動中は印字できない場合がある。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import devices  # noqa: E402

ESC = devices.ESC
GS = devices.GS
FS = devices.FS

WIDTHS = (28, 30, 32, 34, 36)


def ruler_line(n):
    """ちょうどn桁の検証行。10桁ごとに区切りが分かる数字列+右端にEND(半角4桁)。"""
    body = ""
    while len(body) < n - 4:
        block = str((len(body) // 10 + 1) % 10) * 9 + "|"   # 111111111|222222222|...
        body += block[:n - 4 - len(body)]
    return body + "=END"


def build_bytes():
    def sj(text):
        return text.encode("shift_jis", "replace")

    buf = bytearray()
    buf += ESC + b"@"
    buf += FS + b"C" + b"\x01"
    buf += FS + b"&"
    buf += sj("レシート桁数テスト\n")
    buf += sj("折り返さず1行で「END」まで\n")
    buf += sj("印字された最大の桁数を\n")
    buf += sj("教えてください\n")
    buf += sj("-" * devices.RECEIPT_WIDTH + "\n\n")
    for n in WIDTHS:
        line = ruler_line(n)
        assert len(line) == n
        buf += sj(f"[{n}桁]\n")
        buf += sj(line + "\n\n")
    buf += FS + b"."
    buf += b"\n\n\n\n\n\n"
    buf += GS + b"V" + b"\x00"
    return bytes(buf)


def main():
    print("=" * 48)
    print("  レシート桁数(印字幅)確定テスト")
    print("=" * 48)
    print(f"現在の設定: RECEIPT_WIDTH={devices.RECEIPT_WIDTH}桁 / PAPER_DOTS={devices.PAPER_DOTS}ドット")
    print(f"印字する桁数: {' / '.join(str(n) for n in WIDTHS)}(各行の右端に END)")
    print("見方: ENDまで1行に収まった最大の桁数が答え。")
    print("      折り返して2行になった/右端が欠けた桁数はNG。")
    print()
    if input("印字しますか? (y/N): ").strip().lower() != "y":
        print("中止しました。")
        return
    data = build_bytes()
    print(f"→ 送信します({len(data):,}バイト)...")
    try:
        via = devices._send_to_printer(data)
        print(f"   送信完了(経路: {via})")
        print()
        print("★ 写真を撮って「◯桁までOK」と伝えてください。")
        print("  RECEIPT_WIDTH と PAPER_DOTS(=桁数×12)を確定して反映します。")
    except Exception as e:  # noqa: BLE001
        print("[エラー] 印字できませんでした:", e)
        print("  ・宝飾ナビが起動中だとCOMを開けない場合があります")
        print("  ・Windowsの印刷キューが詰まっていないか確認してください")
        print(f"  ・プリンター名の設定: {devices.PRINTER_NAME} / COM: {devices.PRINTER_COM}")


if __name__ == "__main__":
    main()
