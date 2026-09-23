#!/bin/bash
# ★Mac用。店外イベント(催事)にMacを持って行き、同じWi-Fiのスマホ・iPadからも
#   トキワを開けるようにする起動です。UTF-8 + 改行LF で保存すること。
#
# ★この起動は「案A(見るだけ)」用です。
#   イベント中の会計はMacで打たず、売れたものは紙に控えて、
#   店に戻ってから本番機の「過去の日付で登録する」で打ちます。
#   理由: 店のデータとMacのデータが枝分かれすると、後から合体できないため。
#
# ・機器(レシート・ドロワー・カード)は使いません(レジPCにしか繋がっていないため)。
# ・サンプルデータは作りません。db/tokiwa.db が無ければ止まります
#   (偽のデータが本物と混ざる事故を防ぐため)。
cd "$(dirname "$0")/../.." || exit 1

PORT=8760

echo "============================================"
echo "  トキワ 【店外イベント】で起動します"
echo "============================================"
echo
echo "  ・同じWi-Fiのスマホ・iPad・PCからも開けます"
echo "  ・レシート・ドロワー・カードは使えません(機器モードOFF)"
echo
echo "  ★イベント中は【会計を打たないでください】(見るだけ)"
echo "    売れたものは紙に控えて、店に戻ってから本番機で"
echo "    「過去の日付で登録する」で打ちます。"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "[エラー] python3 が見つかりません。"
  echo "  ターミナルで  xcode-select --install  を実行して入れてください。"
  echo
  read -r -p "Enterキーで閉じます..." _
  exit 1
fi

# ★本番のデータが入っていなければ起動しない(サンプルは作らない)
if [ ! -f "db/tokiwa.db" ]; then
  echo "[中止] db/tokiwa.db がありません。"
  echo
  echo "  店のPCから db/tokiwa.db をコピーして、このMacの"
  echo "  「$(pwd)/db/」の中に入れてから、もう一度実行してください。"
  echo "  ※コピーする前に、店のPCで バックアップ.bat を実行しておいてください。"
  echo
  read -r -p "Enterキーで閉じます..." _
  exit 1
fi

# スマホから開くURL。app.py も起動時に出すが、Wi-Fiによっては推測を外すので
# Mac自身が持っているアドレスも先に並べておく(どれかで繋がる)
echo "--------------------------------------------"
echo " スマホ・iPad からは次のURLで開きます:"
for IF in en0 en1 en2 bridge100; do
  IP=$(ipconfig getifaddr "$IF" 2>/dev/null)
  [ -n "$IP" ] && echo "   http://$IP:$PORT/    ($IF)"
done
echo "   ※どれで繋がるかは、そのWi-Fiによって変わります。上から順に試してください。"
echo "   ※Macとスマホが【同じWi-Fi】につながっている必要があります。"
echo "--------------------------------------------"
echo
echo " 止める時は このウィンドウで Control+C を押します。"
echo " ★このウィンドウを閉じる・Macを閉じる(スリープ)と、スマホから見えなくなります。"
echo

( sleep 2; open "http://localhost:$PORT" >/dev/null 2>&1 ) &

# caffeinate: 動かしている間だけMacを寝かせない(スリープするとスマホから切れるため)
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -i python3 server/app.py lan "$PORT"
else
  python3 server/app.py lan "$PORT"
fi

echo
read -r -p "サーバーが終了しました。Enterキーで閉じます..." _
