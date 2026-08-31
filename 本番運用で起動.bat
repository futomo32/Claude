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

rem ---- 画面を持たない Python を探す(黒い画面を出さずに動かすため)----
rem   店から「黒い画面が出ているのが違和感」との声。pythonw は画面を作らない。
rem   ★見つからなければ通常のPythonにそのまま落とす(画面は出るが動く方を優先)。
rem   隠せるようになったのは動作ログ(logs\エラー_今日.txt)を入れたから。
rem   以前は黒い画面がエラーの唯一の出口だった。
set "PYW="
where pyw >nul 2>nul && set "PYW=pyw -3"
if not defined PYW ( where pythonw >nul 2>nul && set "PYW=pythonw" )
if not defined PYW set "PYW=%PY%"
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

rem ---- サーバーを起動(lan=店内共有 / kiki=機器ON)。黒い画面は出さない ----
echo トキワサーバーを起動しています...
start "" %PYW% server\app.py lan kiki

rem ---- ★本当に起動したかを確認する ----
rem   画面を隠すと、起動に失敗しても誰も気づけない。朝レジを開けて初めて分かる、では困る。
rem   8760番に繋がるかを数秒おきに確かめ、駄目なら「その時だけ」画面を出して止まる。
set "TRY=0"
:WAITLOOP
timeout /t 1 /nobreak >nul
set /a TRY+=1
where powershell >nul 2>nul
if errorlevel 1 goto NOCHECK
powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient; try{$c.Connect('127.0.0.1',8760);$c.Close();exit 0}catch{exit 1}" >nul 2>nul
if not errorlevel 1 goto STARTED
if !TRY! lss 20 goto WAITLOOP
goto FAILED

:NOCHECK
rem PowerShell が無い環境では確認できないので、少し待って開くだけにする
timeout /t 3 /nobreak >nul

:STARTED
start "" "http://localhost:8760/"
endlocal
exit /b 0

:FAILED
echo.
echo ============================================
echo  [エラー] トキワが起動できませんでした。
echo ============================================
echo.
echo  原因の手がかりは次のファイルに残っています:
echo     logs\エラー_今日.txt
echo.
echo  よくある原因:
echo   ・既にトキワが動いている(二重起動はサーバー側で止めています)
echo   ・db\tokiwa.db が壊れている
echo   ・Python の部品が足りない
echo.
echo  画面を出して原因を見るには「機器ありで起動.bat」で起動してください。
echo  黒い画面にエラーがそのまま表示されます。
echo.
pause
endlocal
exit /b 1

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
