# -*- coding: utf-8 -*-
"""店舗の固定情報(唯一の正)。店名・電話・インボイス登録番号・振込先はここだけを直す。

ここの値は自動で次の場所に反映される:
- レシート印字(server/devices.py: 店名フォールバック・TEL・登録番号)
- 帳票印刷(見積書・請求書・修理伝票): app.py が window.TOKIWA_STORE として画面に注入し、
  tokiwa-ui.html がヘッダ・登録番号・振込先口座に使う
※単体HTML(サーバー無しのプレビュー)だけは画面側の見本値が表示される。
  実運用は必ずサーバー経由なので、この値が使われる。
"""

STORE_NAME = "宝石・メガネ・時計 ヤナセ"   # 正式店名(帳票の発行元・レシートのロゴ代替)
STORE_TEL = "0565-32-0688"                  # 電話番号(レシートに印字)
SENDER_POSTAL = "471-0029"                  # ご依頼主郵便番号(クロネコB2のDM便書き出しに使用)
SENDER_ADDRESS = "豊田市桜町1-18"            # ご依頼主住所(クロネコB2のDM便書き出しに使用)
INVOICE_REG_NO = "T1810816014712"           # インボイス登録番号(適格請求書発行事業者)
BANK_LINES = [                              # 請求書に印字する振込先(1行ずつ)
    "豊田信用金庫　普通預金",
    "店番 011　口座番号 9264690",
    "名義　築瀬 智宏",
]


def as_dict():
    """画面へ注入する形(app.py が window.TOKIWA_STORE に入れる)。"""
    return {"name": STORE_NAME, "tel": STORE_TEL,
            "invoice_no": INVOICE_REG_NO, "bank_lines": list(BANK_LINES)}
