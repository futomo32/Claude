# -*- coding: utf-8 -*-
"""ロゴの中央寄せ確定テスト(目盛りで印字幅を実測 + オフセット見比べ)。

背景: ロゴを幅いっぱい(336ドット)で印字すると左に寄る症状が出た(2026-07-30)。
      原因は server/devices.py の PAPER_DOTS(=336)が実機の本当の印字可能幅と
      合っていないため。336ドットのロゴでは中央寄せの余白が0になり、実際の印字幅が
      336より広いと余りが全部右に集まって「左寄り」に見える。

このテストで2つを一度に確定する:
  (1) 目盛り印字 …… 印字可能幅が実際に何ドットあるか(紙で途切れた位置で分かる)
  (2) オフセット見比べ …… 同じロゴを 0/8/16/24/32 ドット右へずらして印字。中央に見えた番号を選ぶ

★1枚で決まるので、店側の作業は実行して写真を1枚撮るだけ。
  結果を伝えてもらえば PAPER_DOTS と LOGO_OFFSET_DOTS を確定して反映する。

  python3 hardware/logo_center_test.py

注意: Pillow が必要(pip install pillow)。宝飾ナビ起動中は印字できない場合がある。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import devices  # noqa: E402  本番と同じ変換処理を使う

ESC = devices.ESC
GS = devices.GS
FS = devices.FS

RULER_DOTS = 440        # 目盛りの長さ(ドット)。実機の印字幅より確実に長くして「どこで切れるか」を見る
OFFSETS = (0, 8, 16, 24, 32)   # 見比べる右ずらし量(ドット)。8ドット≒1mm


def ruler_image():
    """目盛り画像を作る。1mmごとに小さい目盛り、5mmで中、10mmで長い目盛り+ドット数の数字。
    印字可能幅を超えた部分は印字されないため、途切れた位置で実際の幅が分かる。"""
    from PIL import Image, ImageDraw
    h = 46
    img = Image.new("1", (RULER_DOTS, h), 1)   # 1=白
    d = ImageDraw.Draw(img)
    base = h - 1
    d.line([(0, base), (RULER_DOTS - 1, base)], fill=0, width=2)   # 下端の基準線
    for x in range(0, RULER_DOTS, 8):          # 8ドット=1mm
        length = 6
        if x % 40 == 0:
            length = 12                        # 5mm
        if x % 80 == 0:
            length = 22                        # 10mm
        d.line([(x, base - length), (x, base)], fill=0)
    for x in range(0, RULER_DOTS, 80):         # 10mmごとにドット数を印字
        d.text((x + 2, 2), str(x), fill=0)
    return img


def build_bytes():
    def sj(text):
        return text.encode("shift_jis", "replace")

    buf = bytearray()
    buf += ESC + b"@"
    buf += FS + b"C" + b"\x01"
    buf += FS + b"&"
    buf += sj(devices._center("中央寄せ確定テスト") + "\n")
    buf += sj("-" * devices.RECEIPT_WIDTH + "\n")

    # ── (1) 目盛り: 印字可能幅の実測 ──
    buf += sj("【1】目盛り(印字幅の実測)\n")
    buf += sj("数字が途切れた位置を教えて\n")
    buf += sj("ください(例: 384で切れた)\n")
    try:
        buf += devices._raster_from_image(ruler_image(), 0)
    except ImportError:
        raise RuntimeError("Pillow が必要です: pip install pillow")
    buf += b"\n"
    buf += sj("-" * devices.RECEIPT_WIDTH + "\n")

    # 文字の右端も確認できるように、現在の桁数いっぱいの行を出す
    buf += sj("【2】文字の右端(28桁)\n")
    buf += sj("=" * devices.RECEIPT_WIDTH + "\n")
    buf += sj("↑この線が紙に収まっているか\n")
    buf += sj("-" * devices.RECEIPT_WIDTH + "\n")

    # ── (3) ロゴを各オフセットで印字 ──
    buf += sj("【3】ロゴの位置(中央に見える番号)\n")
    buf += sj("-" * devices.RECEIPT_WIDTH + "\n")
    orig = (devices.LOGO_OFFSET_DOTS, devices.LOGO_MAX_H, devices.LOGO_DITHER, devices.LOGO_THRESHOLD)
    try:
        devices.LOGO_MAX_H = 336        # 採用した「G」の設定で確認する
        devices.LOGO_DITHER = False
        devices.LOGO_THRESHOLD = 160
        for i, off in enumerate(OFFSETS, 1):
            devices.LOGO_OFFSET_DOTS = off
            raster = devices._logo_raster()
            if raster is None:
                raise RuntimeError("ロゴを変換できません(Pillow未導入 or assets/logo.png が読めない)")
            buf += sj(f"({i}) 右へ{off}ドット(約{off / 8:.0f}mm)\n")
            buf += raster
            buf += b"\n"
            buf += sj("-" * devices.RECEIPT_WIDTH + "\n")
    finally:
        devices.LOGO_OFFSET_DOTS, devices.LOGO_MAX_H, devices.LOGO_DITHER, devices.LOGO_THRESHOLD = orig

    buf += sj(devices._center("以上") + "\n")
    buf += FS + b"."
    buf += b"\n\n\n\n\n\n"
    buf += GS + b"V" + b"\x00"
    return bytes(buf)


def main():
    print("=" * 48)
    print("  ロゴ 中央寄せ確定テスト")
    print("=" * 48)
    print("印字するもの:")
    print(f"  【1】目盛り {RULER_DOTS}ドット分 … 印字可能幅の実測(どこで途切れるか)")
    print(f"  【2】{devices.RECEIPT_WIDTH}桁いっぱいの線 … 文字の右端が収まっているかの確認")
    print(f"  【3】ロゴを {len(OFFSETS)}種類の位置で … {'/'.join(str(o) for o in OFFSETS)} ドット右へずらす")
    print()
    print(f"現在の設定: PAPER_DOTS={devices.PAPER_DOTS} LOGO_MAX_H={devices.LOGO_MAX_H}"
          f" LOGO_OFFSET_DOTS={devices.LOGO_OFFSET_DOTS}")
    print("※紙を約20cm使います。")
    print()

    if input("印字しますか? (y/N): ").strip().lower() != "y":
        print("中止しました。")
        return

    try:
        data = build_bytes()
    except RuntimeError as e:
        print("[エラー]", e)
        return

    print(f"→ 送信します({len(data):,}バイト)...")
    try:
        via = devices._send_to_printer(data)
        print(f"   送信完了(経路: {via})")
        print()
        print("★ レシートの写真を撮って、次の2つを教えてください:")
        print("  ① 目盛りの数字がどこで途切れたか(例: 384 は出たが 400 は出ていない)")
        print("  ② ロゴが一番中央に見えた番号((1)〜(5))")
        print("  → PAPER_DOTS と LOGO_OFFSET_DOTS を確定して反映します。")
        print("  ※【2】の線が紙からはみ出ている/余りすぎている場合も教えてください(桁数を直します)")
    except Exception as e:  # noqa: BLE001
        print("[エラー] 印字できませんでした:", e)
        print("  ・宝飾ナビが起動中だとCOMを開けない場合があります(双方向サポートON時)")
        print(f"  ・プリンター名の設定: {devices.PRINTER_NAME} / COM: {devices.PRINTER_COM}")


if __name__ == "__main__":
    main()
