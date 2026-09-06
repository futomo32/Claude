@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
cd /d "%~dp0..\.."
title トキワ ポイント区分しらべ

echo ============================================
echo   ポイント履歴の「区分」の内訳を出します
echo ============================================
echo.
echo  区分が「1」「8」のような数字のまま出ているので、
echo  日本語(繰越/修正/購入…)に直すための対応表を作ります。
echo.
echo  ・読むだけです。データは1文字も変更しません
echo  ・お客様の情報は表示しません(件数だけ)
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto NOPYTHON

%PY% scripts\fix_point_dates.py --kbn

echo.
echo  出てきた一覧を、宝飾ナビのポイント履歴の画面(区分の列)と
echo  見比べて、そのまま送ってください。

echo.
pause
exit /b 0

:NOPYTHON
echo.
echo  [エラー] Python が見つかりません。
echo  Microsoft Store から「Python 3」を入れてから、もう一度実行してください。
echo.
pause
exit /b 1
