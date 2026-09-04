#!/bin/bash
# ★Mac(開発環境)用。お試し・確認のための起動。機器(レシート・カード)は使いません。
#   UTF-8 + 改行LF で保存すること。
cd "$(dirname "$0")/../.." || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "[エラー] python3 が見つかりません。"
  echo "  ターミナルで  xcode-select --install  を実行して入れてください。"
  echo
  read -r -p "Enterキーで閉じます..." _
  exit 1
fi

echo "============================================"
echo "  トキワを起動します（機器モード OFF）"
echo "============================================"
echo
echo "  ブラウザで http://localhost:8760 を開いてください。"
echo "  止める時は このウィンドウで Control+C を押します。"
echo

# 起動が落ち着いた頃にブラウザを開く（サーバーはこのウィンドウで動かし続ける）
( sleep 2; open "http://localhost:8760" >/dev/null 2>&1 ) &

python3 server/app.py
echo
read -r -p "サーバーが終了しました。Enterキーで閉じます..." _
