@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
rem   ".." が1つだと ツール\ 止まりで server\ や db\ を見失う(2026-09-01 修正)
cd /d "%~dp0..\.."
title トキワ 台帳の行数しらべ

echo ============================================
echo   11台帳(xlsx)の行数を数えます
echo ============================================
echo.
echo  取り込みのあとの「答え合わせ」に使います。
echo  ここで出た行数を、取り込みのときに出た件数と見比べてください。
echo.
echo  ・data\real\xlsx\ の xlsx を読みます
echo  ・直下 data\real\ に置いたままでも読みます
echo  ・表示するのは行数と列数だけです。お客様の情報は表示しません
echo.
echo  【見比べかた】
echo   顧客・商品・売掛・ポイントは一致するはずです。
echo   販売台帳と処方箋はズレていて正常です。
echo   販売はトキワ側で伝票と明細に分けているためです。
echo   処方箋は宝飾品の誤登録を除いているためです。
echo.

rem ---- Python を探す(py 優先、無ければ python / python3)----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY goto NOPYTHON

rem ---- xlsx を読む部品が入っているか先に確かめる ----
%PY% -c "import openpyxl" >nul 2>nul
if errorlevel 1 goto NOOPENPYXL

%PY% scripts\diag_real_xlsx.py
if errorlevel 1 goto FAILED
goto END

:NOPYTHON
echo.
echo  [エラー] Python が見つかりません。
echo  https://www.python.org/downloads/windows/ からインストールし、
echo  「Add python.exe to PATH」に必ずチェックを入れてください。
goto END

:NOOPENPYXL
echo.
echo  [エラー] xlsx を読む部品 openpyxl が入っていません。
echo  下のコマンドをコマンドプロンプトで実行してから、もう一度お試しください。
echo.
echo      python -m pip install openpyxl
echo.
echo  ※取り込みそのものには要りません。この確認にだけ使います。
goto END

:FAILED
echo.
echo  [エラー] 実行に失敗しました。上の表示を確認してください。
echo  11台帳の xlsx が data\real\xlsx\ に置かれているか確かめてください。

:END
echo.
pause
