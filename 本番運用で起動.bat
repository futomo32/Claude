@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title トキワ 本番運用

echo ============================================
echo   トキワ 【本番運用】で起動します
echo ============================================
echo.
echo  ・レシート印字・ドロワー・カード書込を行います(機器ON)
echo  ・他のPC・スマホ・iPadからも使えます(店内共有)
echo  ・毎日の営業はこのバッチから起動してください
echo.
echo  注意: 宝飾ナビが機器(COMポート)を使っていると通信できません。
echo        宝飾ナビを終了してから起動してください。
echo.

rem ---- Python を探す(py 優先、無ければ python / python3)----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY goto NOPYTHON
echo 使用する Python: %PY%
%PY% --version
if errorlevel 1 goto NOPYTHON
echo.

rem ---- ★本番用はサンプルDBを作らない(本物のデータと混ざる事故を防ぐため)----
if not exist "db\tokiwa.db" goto NODB

rem ---- 既にトキワが動いていないか確認 ----
rem   古い「機器OFF」のサーバーが残っていると、ブラウザは古い方に繋がる。
rem   画面は普通に開くのに「レシートが出ない」ことになるため、ここで気づけるようにする。
rem   ※これは案内用。実際に二重起動を止めるのはサーバー側(app.py の already_running)。
rem     手打ちで起動した場合もそちらで止まる。
netstat -an | findstr ":8760" >nul 2>nul
if errorlevel 1 goto PORTOK
echo.
echo  [注意] すでに 8760番 が使われています。トキワが起動中の可能性があります。
echo         先に動いているものが「機器OFF」だと、レシートもドロワーも動きません。
echo         このまま進めても、二重に起動しないようサーバー側で止まります。
echo.
echo   1: 中止する ... 先に「トキワ サーバー」のウィンドウを全部閉じる  ← おすすめ
echo   2: このまま続ける
echo.
set "SEL=1"
set /p SEL="どちらにしますか? [1]: "
if not "%SEL%"=="2" goto ABORT
:PORTOK

rem ---- クロネコB2の書き出しに必要な部品の確認(無くても起動はします)----
rem ★ここは if ( ) のブロックにしないこと。ブロックの中の echo に丸括弧が入ると
rem   cmd がそこでブロックを閉じてしまい、バッチ全体が動かなくなる(2026-08-29 の不具合)
%PY% -c "import openpyxl" >nul 2>nul
if not errorlevel 1 goto XLOK
echo [お知らせ] クロネコB2の書き出しに必要な部品 openpyxl が入っていません。
echo            DM便の書き出しを使う時は、次を一度だけ実行してください:
echo              %PY% -m pip install openpyxl
echo.
:XLOK

rem ---- サーバーを別ウィンドウで起動(lan=店内共有 / kiki=機器ON)----
echo トキワサーバーを起動します...
start "トキワ サーバー 本番運用(このウィンドウを閉じると停止します)" %PY% server\app.py lan kiki

timeout /t 3 >nul
echo ブラウザを開きます: http://localhost:8760/
start "" "http://localhost:8760/"
echo.
echo --------------------------------------------
echo  起動しました。
echo  ★他の端末(iPad・スマホ・別のPC)から開くURLは
echo    「トキワ サーバー」ウィンドウに表示されています
echo    (http://192.168.〇.〇:8760/ の形)。
echo  ★初回はWindowsファイアウォールの確認が出ます。
echo    「アクセスを許可する」を押してください。
echo  終了するには「トキワ サーバー」ウィンドウを閉じてください。
echo --------------------------------------------
echo.
pause
endlocal
exit /b 0

:ABORT
echo.
echo  中止しました。タスクバーの「トキワ サーバー」のウィンドウを全部閉じてから、
echo  もう一度このバッチを実行してください。
echo.
pause
endlocal
exit /b 1

:NODB
echo.
echo [中止] データベース(db\tokiwa.db)がありません。
echo   本番用のバッチは、サンプルデータを作りません
echo   (お試し用の偽データが本物と混ざる事故を防ぐためです)。
echo.
echo   宝飾ナビのデータを取り込んでから、もう一度起動してください:
echo     %PY% scripts\import_csv.py data\real\csv
echo.
echo   ※お試しで動かしたいだけなら「トキワ起動.bat」を使ってください。
echo.
pause
endlocal
exit /b 1

:NOPYTHON
echo.
echo [エラー] 使用できる Python が見つかりませんでした。
echo.
echo   対処:
echo   1) https://www.python.org/downloads/windows/ から Python をインストール
echo      インストールの最初の画面で
echo      「Add python.exe to PATH」に必ずチェックを入れてください。
echo   2) インストール後、もう一度このバッチをダブルクリック
echo.
pause
endlocal
exit /b 1
