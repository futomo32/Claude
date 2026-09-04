#!/bin/bash
# ★Mac(開発環境)用。UTF-8 + 改行LF で保存すること。
cd "$(dirname "$0")/../.." || exit 1

echo "============================================"
echo "  仕入先コードを実際に入れます"
echo "============================================"
echo
echo " ・書き込む前に自動でバックアップを取ります。"
echo " ・既にコードが入っている仕入先は上書きしません。"
echo " ・同じコードが2つに付く場合は入れず、一覧に出します。"
echo
echo " ★先に「1_仕入先コードを下読み.command」で件数を確認してください。"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "[エラー] python3 が見つかりません。"
  echo "  ターミナルで  xcode-select --install  を実行して入れてください。"
  echo
  read -r -p "Enterキーで閉じます..." _
  exit 1
fi

read -r -p "本当に書き込みますか？ yes と入力してください: " ans
if [ "$ans" != "yes" ]; then
  echo "中止しました。"
  echo
  read -r -p "Enterキーで閉じます..." _
  exit 0
fi

python3 scripts/fill_supplier_codes.py --apply
echo
read -r -p "Enterキーで閉じます..." _
