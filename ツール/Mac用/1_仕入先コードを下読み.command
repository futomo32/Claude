#!/bin/bash
# ★Mac(開発環境)用。ダブルクリックで動きます。
#   Windowsの .bat と違い、この .command は **UTF-8 + 改行LF** で保存すること。
#   このファイルは ツール/Mac用/ の下(2階層)にあるので、2つ上のトキワ本体へ移動してから動かす。
cd "$(dirname "$0")/../.." || exit 1

echo "============================================"
echo "  仕入先コードの下読み（何も書き換えません）"
echo "============================================"
echo
echo " ・宝飾ナビの m_siiresaki.csv と仕入先マスタを名前で突き合わせ、"
echo "   コードを何件入れられるかを数えるだけです。"
echo " ・データベースは一切変更しません。"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "[エラー] python3 が見つかりません。"
  echo "  ターミナルで  xcode-select --install  を実行して入れてください。"
  echo
  read -r -p "Enterキーで閉じます..." _
  exit 1
fi

python3 scripts/fill_supplier_codes.py
echo
echo "--------------------------------------------"
echo " 数字を確認してください。問題なければ"
echo " 「2_仕入先コードを入れる.command」を実行します。"
echo
read -r -p "Enterキーで閉じます..." _
