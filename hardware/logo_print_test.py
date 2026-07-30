# -*- coding: utf-8 -*-
"""レシートのロゴ画質・サイズの見比べ印字(1枚に全パターンを並べる)。

目的: ロゴの「荒さ」をどの設定で解消できるかを実機で決める。画面では判断できないため
      (サーマル印字は見え方が違う)、実物を1枚出して見比べるのが唯一確実な方法。

★1回の実行で全パターンを1枚に印字するので、店側の作業は「実行して写真を1枚撮る」だけ。
  写真を見て良かったパターンの設定を server/devices.py の定数に反映する。

  python3 hardware/logo_print_test.py        # 全パターン(既定)
  python3 hardware/logo_print_test.py A C    # 指定パターンだけ(紙の節約)

変えている3つの設定(server/devices.py):
  LOGO_DITHER    … False=しきい値(ベタ塗り・線画に強い) / True=ディザ(濃淡・グラデに強い)
  LOGO_MAX_H     … ロゴ高さの上限(ドット)。8ドット≒1mm。正方形ロゴではここが実サイズを決める
  LOGO_THRESHOLD … しきい値方式の白黒境界(0-255)。上げると濃く・太く印字される

注意: 宝飾ナビ起動中はプリンターを使えないことがある(双方向サポートON時)。
      Pillow が必要: pip install pillow
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import devices  # noqa: E402  本番と同じ変換処理(_logo_raster)を使って検証する

ESC = devices.ESC
GS = devices.GS
FS = devices.FS

# (記号, 説明, ディザ, 高さ上限, しきい値)
PATTERNS = [
    ("A", "現状(基準)",       False, 150, 160),
    ("B", "ディザ",           True,  150, 160),
    ("C", "大きめ",           False, 200, 160),
    ("D", "大きめ+ディザ",    True,  200, 160),
    ("E", "大きめ+薄め",      False, 200, 130),
    ("F", "大きめ+濃め",      False, 200, 190),
    # 正方形ロゴでは高さ上限が実サイズを決めるため、紙幅いっぱい(336ドット≒42mm)も比較対象に入れる
    ("G", "最大(幅いっぱい)",  False, 336, 160),
]


def logo_dots(max_h):
    """印字される実寸(ドット)を計算する。devices._logo_raster と同じ計算(表示用)。"""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(devices.LOGO_PATH)
        scale = min(devices.LOGO_DOTS / img.width, max_h / img.height)
        w = max(8, int(img.width * scale) // 8 * 8)
        h = max(1, round(img.height * w / img.width))
        return w, h, img.width, img.height
    except Exception:  # noqa: BLE001
        return None


def build_bytes(selected):
    """選んだパターンを1枚に並べたESC/POSバイト列を作る。"""
    def sj(text):
        return text.encode("shift_jis", "replace")

    buf = bytearray()
    buf += ESC + b"@"
    buf += FS + b"C" + b"\x01"
    buf += FS + b"&"
    buf += sj(devices._center("ロゴ印字テスト") + "\n")
    buf += sj("-" * devices.RECEIPT_WIDTH + "\n")
    buf += sj("良かった記号を伝えてください\n")
    buf += sj("-" * devices.RECEIPT_WIDTH + "\n\n")

    # 設定を一時的に差し替えて変換する。終わったら必ず元に戻す
    orig = (devices.LOGO_DITHER, devices.LOGO_MAX_H, devices.LOGO_THRESHOLD)
    try:
        for key, label, dither, max_h, th in selected:
            devices.LOGO_DITHER = dither
            devices.LOGO_MAX_H = max_h
            devices.LOGO_THRESHOLD = th
            raster = devices._logo_raster()
            if raster is None:
                raise RuntimeError("ロゴを変換できません(Pillow未導入 or assets/logo.png が読めない)")
            dots = logo_dots(max_h)
            spec = f"{'ディザ' if dither else 'しきい値' + str(th)}"
            if dots:
                spec += f" {dots[0]}x{dots[1]}dot(約{dots[1] // 8}mm)"
            buf += sj(f"[{key}] {label}\n")
            buf += sj(f"    {spec}\n")
            buf += raster
            buf += b"\n"
            buf += sj("-" * devices.RECEIPT_WIDTH + "\n")
    finally:
        devices.LOGO_DITHER, devices.LOGO_MAX_H, devices.LOGO_THRESHOLD = orig

    buf += sj(devices._center("以上") + "\n")
    buf += FS + b"."
    buf += b"\n\n\n\n\n\n"        # カッターは印字ヘッドより上にあるため送りを多めに
    buf += GS + b"V" + b"\x00"    # フルカット
    return bytes(buf)


def main():
    print("=" * 48)
    print("  レシート ロゴ印字テスト(見比べ用・1枚に全パターン)")
    print("=" * 48)

    keys = [a.upper() for a in sys.argv[1:] if a.upper() in {p[0] for p in PATTERNS}]
    selected = [p for p in PATTERNS if not keys or p[0] in keys]

    dots = logo_dots(devices.LOGO_MAX_H)
    if dots is None:
        print("[エラー] ロゴを読み込めません。")
        print("  ・Pillow が必要です: pip install pillow")
        print(f"  ・ロゴの場所: {os.path.abspath(devices.LOGO_PATH)}")
        return
    print(f"元のロゴ: {dots[2]} x {dots[3]} px")
    print(f"印字幅の上限: {devices.LOGO_DOTS}ドット(紙の印字幅 {devices.PAPER_DOTS}ドット)")
    print()
    print("印字するパターン:")
    for key, label, dither, max_h, th in selected:
        d = logo_dots(max_h)
        size = f"{d[0]}x{d[1]}dot(約{d[1] // 8}mm)" if d else "?"
        print(f"  [{key}] {label:14} {'ディザ' if dither else 'しきい値' + str(th):10} {size}")
    print()
    print(f"※紙を約{len(selected) * 3 + 4}cm使います。少なくしたい場合は記号を指定して実行:")
    print("   python3 hardware/logo_print_test.py A C D")
    print()

    if input("印字しますか? (y/N): ").strip().lower() != "y":
        print("中止しました。")
        return

    try:
        data = build_bytes(selected)
    except RuntimeError as e:
        print("[エラー]", e)
        return

    print(f"→ 送信します({len(data):,}バイト)...")
    try:
        via = devices._send_to_printer(data)
        print(f"   送信完了(経路: {via})")
        print()
        print("★ 印字されたレシートの写真を撮って共有してください。")
        print("  良かった記号(例: D)を伝えれば server/devices.py の定数に反映します。")
        print("  判断のポイント: 文字や線のフチがガタガタしていないか / 濃さが適切か / 大きさ")
    except Exception as e:  # noqa: BLE001
        print("[エラー] 印字できませんでした:", e)
        print("  ・宝飾ナビが起動中だとCOMを開けない場合があります(双方向サポートON時)")
        print(f"  ・プリンター名の設定: {devices.PRINTER_NAME} / COM: {devices.PRINTER_COM}")


if __name__ == "__main__":
    main()
