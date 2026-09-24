#!/bin/bash
# ★Mac用。催事(店外イベント)から帰ってきたら、消す前にこれを1回押します。
#   UTF-8 + 改行LF で保存すること。
#
# このMacのデータに「催事の日以降に書かれた記録」が無いかを数えるだけです。
# ★読むだけで、データは一切書き換えません。
#
#   0件 … そのまま db/tokiwa.db を消して終わりです
#   1件以上 … このMacにだけ残っている記録です。本番機で入れ直してから消します
cd "$(dirname "$0")/../.." || exit 1

echo "============================================"
echo "  催事のあと確認（読むだけ・書き換えません）"
echo "============================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "[エラー] python3 が見つかりません。"
  echo "  ターミナルで  xcode-select --install  を実行して入れてください。"
  echo
  read -r -p "Enterキーで閉じます..." _
  exit 1
fi

if [ ! -f "db/tokiwa.db" ]; then
  echo "[中止] db/tokiwa.db がありません。"
  echo "  すでに消したあとであれば、確認は不要です。"
  echo
  read -r -p "Enterキーで閉じます..." _
  exit 1
fi

echo " 催事へ持ち出した日（出発した日）を入れてください。"
echo " 例: 2026-10-01"
echo
read -r -p " 持ち出した日 > " SINCE
echo

if [ -z "$SINCE" ]; then
  echo "[中止] 日付が入力されませんでした。"
  echo
  read -r -p "Enterキーで閉じます..." _
  exit 1
fi

python3 scripts/check_offsite_writes.py --since "$SINCE"
echo
read -r -p "Enterキーで閉じます..." _
