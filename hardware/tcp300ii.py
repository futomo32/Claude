# -*- coding: utf-8 -*-
"""TCP300II サーマルリライトカード R/W ドライバ(トキワ用・pyserial)。

スター精密 TCP300II コマンド仕様書に基づく最小実装。
本番機実測: COM3 / 本機は1トラック機(TCP300II)→ 磁気は「トラック2」のみ。

フレーム : コマンド  = STX | cmd | data | ETX | BCC
           レスポンス = STX | cmd | status | data | ETX | BCC
BCC      : コマンド〜ETX の XOR
制御文字 : STX=02 ETX=03 ACK=06 NAK=15 DLE=10

安全方針: 既定は「読み取り」のみ使用。磁気ライト(set_track2/write)は
          誤書込防止のため明示的に呼んだ時だけ動く。
"""
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pyserial 未導入環境でも import だけは通す
    serial = None
    list_ports = None

STX = 0x02
ETX = 0x03
ACK = 0x06
NAK = 0x15
DLE = 0x10

STATUS_TEXT = {
    0x20: "正常",
    0x22: "処理対象カード無し",
    0x23: "磁気ストライプ無し(逆差し等)/その他エラー",
    0x31: "パリティエラー",
    0x32: "開始/終了符号なし",
    0x33: "LRCエラー",
    0x34: "異常キャラクタ",
    0x37: "磁気ストライプ書込エラー",
    0x38: "カードジャム",
    0x40: "カバーOPEN",
    0x41: "無効コマンド",
    0x42: "カムモータ異常",
    0x43: "イレースヘッド温度異常",
    0x45: "EEPROMエラー",
    0x4C: "不適合BMPファイルデータ",
    0x51: "展開バッファオーバーフロー",
}


def bcc(payload: bytes) -> int:
    """コマンド〜ETX の排他的論理和。"""
    x = 0
    for b in payload:
        x ^= b
    return x


class TCP300IIError(Exception):
    pass


def find_port():
    """SMJ(スター)らしき仮想COMを推測。見つからなければ None。"""
    if list_ports is None:
        return None
    for p in list_ports.comports():
        blob = ((p.description or "") + " " + (p.hwid or "")).upper()
        if "0519" in blob or "SMJ" in blob or "STAR" in blob:
            return p.device
    return None


class TCP300II:
    def __init__(self, port="COM3", baud=9600, timeout=0.2):
        if serial is None:
            raise TCP300IIError("pyserial が必要です。pip install pyserial を実行してください。")
        self.ser = serial.Serial(port, baud, timeout=timeout)
        self.trace = []  # 通信ログ [('TX'|'RX', hex文字列), ...] デバッグ用

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- 低レベル ----
    def _send_block(self, cmd, data=b""):
        body = bytes([cmd]) + data + bytes([ETX])
        block = bytes([STX]) + body + bytes([bcc(body)])
        self.ser.reset_input_buffer()
        self.trace.append(("TX", block.hex(" ")))
        self.ser.write(block)
        self.ser.flush()

    def _read_byte(self, deadline):
        while time.time() < deadline:
            b = self.ser.read(1)
            if b:
                self.trace.append(("RX", f"{b[0]:02x}"))
                return b[0]
        return None

    def _await_ack(self, cmd, data, deadline, max_resend=3):
        resent = 0
        while True:
            r = self._read_byte(deadline)
            if r is None:
                raise TCP300IIError("ACK応答なし(タイムアウト)")
            if r == ACK:
                return
            if r == NAK:
                if resent >= max_resend:
                    raise TCP300IIError("再送要求(NAK)が続き送信できませんでした")
                resent += 1
                self._send_block(cmd, data)  # 再送
                continue
            if r == DLE:
                raise TCP300IIError("コマンド拒否(DLE)")
            # 古いフレームの残骸などは読み捨てて ACK を待ち続ける

    def _read_frame(self, deadline):
        """STX〜BCC の1フレームを受信し (cmd, status, payload) を返す。
        BCC不一致は NAK を送って再送フレームを受け直す(リトライ)。"""
        for _ in range(4):  # 初回 + 再送3回まで
            # STX を待つ
            while True:
                b = self._read_byte(deadline)
                if b is None:
                    raise TCP300IIError("レスポンス応答なし(タイムアウト)")
                if b == STX:
                    break
            # ETX まで読む
            buf = bytearray()
            while True:
                b = self._read_byte(deadline)
                if b is None:
                    raise TCP300IIError("ETX受信前にタイムアウト")
                if b == ETX:
                    break
                buf.append(b)
            rx_bcc = self._read_byte(deadline)
            calc = bcc(bytes(buf) + bytes([ETX]))
            if rx_bcc is not None and rx_bcc == calc:
                # 正常受信 → ACK 返信
                self.ser.write(bytes([ACK]))
                self.ser.flush()
                cmd = buf[0] if len(buf) >= 1 else None
                status = buf[1] if len(buf) >= 2 else None
                return cmd, status, bytes(buf[2:])
            # BCC不一致 → NAK で再送を要求して受け直す
            try:
                self.ser.write(bytes([NAK]))
                self.ser.flush()
            except Exception:
                pass
        raise TCP300IIError("BCC不一致が続き受信できませんでした")

    def command(self, cmd, data=b"", ack_timeout=5.0, resp_timeout=30.0):
        """1コマンド往復。戻り値 (cmd_echo, status, payload)。
        送ったコマンドと異なるエコーのフレーム(古い再送等)は読み飛ばす。"""
        self._send_block(cmd, data)
        self._await_ack(cmd, data, time.time() + ack_timeout)
        deadline = time.time() + resp_timeout
        while True:
            cmd_echo, status, payload = self._read_frame(deadline)
            if cmd_echo == cmd:
                return cmd_echo, status, payload
            # 混線した別コマンドの応答(ACK済み)は捨てて、目的の応答を待つ

    # ---- 高レベル(読み取り中心) ----
    def read_track2(self, resp_timeout=30.0):
        """第2トラックリード(22h・自動フォーマット識別)。カード挿入を待つ。
        戻り値 (status:int, data:bytes)。status=0x20 が正常。"""
        _, status, payload = self.command(0x22, resp_timeout=resp_timeout)
        return status, payload

    def read_track2_fmt(self, fmt="0", resp_timeout=30.0):
        """第2トラックをフォーマット明示でリード(24h)。fmt: '0'〜'4'。"""
        data = b"2," + fmt.encode("ascii")
        _, status, payload = self.command(0x24, data, resp_timeout=resp_timeout)
        return status, payload

    def status_request(self):
        """ステータス要求(59h)。"""
        _, status, payload = self.command(0x59, resp_timeout=5.0)
        return status, payload

    def rom_version(self):
        _, status, payload = self.command(0x58, resp_timeout=5.0)
        return status, payload

    def eject(self, retries=3):
        """カード排出(50h)。読取直後はDLE拒否されることがある(実機実測)ため、
        少し待ってリトライする。"""
        last = None
        for i in range(retries):
            if i:
                time.sleep(0.6)
            try:
                return self.command(0x50, resp_timeout=10.0)
            except TCP300IIError as e:
                last = e
        raise last

    def cancel_insert_wait(self):
        """カード挿入待ち状態解除(54h・優先コマンド)。"""
        self._send_block(0x54)

    def reset(self):
        """リセット(5Fh)。初期化に約3秒。"""
        self._send_block(0x5F)
        time.sleep(3.2)

    # ---- 磁気ライト(誤書込防止のため既定では使わない) ----
    def _set_track2(self, data: bytes):
        """第2トラックのライトデータ設定(3Ch)。データは 01h〜7Eh(02h/03h除く)。"""
        _, status, _ = self.command(0x3C, data, resp_timeout=10.0)
        return status

    def write_track2(self, data: bytes, resp_timeout=30.0):
        """磁気ライト: (1)3Ch でデータ設定 → (2)31h で書込実行(トラック2)。
        ★実機での動作未検証。使用前に読み取りで疎通を確認してから。"""
        st = self._set_track2(data)
        if st != 0x20:
            raise TCP300IIError("データ設定失敗: " + status_text(st))
        _, status, _ = self.command(0x31, b"2", resp_timeout=resp_timeout)
        return status


def status_text(code):
    if code is None:
        return "(なし)"
    return STATUS_TEXT.get(code, f"未定義(0x{code:02X})")
