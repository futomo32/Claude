@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Tokiwa Update And Start

rem ============================================================
rem  トキワ 更新して起動.bat (2026-10-08 店の指定)
rem   「トキワ停止して更新.bat」→「本番運用で起動.bat」を1回のクリックで通す。
rem   ★元の2つのバッチはそのまま残してある(更新だけ・起動だけをしたい時に使う)。
rem
rem  設計の決め事:
rem   ・更新に失敗しても**起動は必ずする**。営業が止まる方が困るため。
rem     ただし「更新できていない」ことは必ず画面に出す(黙って古いまま動かさない)。
rem   ・★更新がぶつかった時(店のPCで直接コミットした等)は、**英語のエラーを
rem     繰り返さずに日本語で説明して止める**。2026-10-01に、同じ英語のエラーが
rem     4回出て画面が埋まり、何が起きたか分からない事故があったため。
rem   ・再試行はネットワークの不調だけを想定して2回まで(2秒・4秒)。
rem ============================================================

echo ============================================
echo   トキワ 【更新して起動】します
echo ============================================
echo.
echo  (1) 動いているトキワを止める
echo  (2) 最新版を取り込む（git pull）
echo  (3) 本番運用で起動する（レシート・ドロワー・カードON／店内共有ON）
echo.
echo  ・お店のデータ（db フォルダ）には触りません
echo.

rem ---- Python を探す(py 優先、無ければ python / python3)----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY goto NOPYTHON
%PY% --version >nul 2>nul
if errorlevel 1 goto NOPYTHON

rem ---- 画面を持たない Python を探す(黒い画面を出さずに動かすため)----
set "PYW="
where pyw >nul 2>nul && set "PYW=pyw -3"
if not defined PYW ( where pythonw >nul 2>nul && set "PYW=pythonw" )
if not defined PYW set "PYW=%PY%"

rem ============================================================
rem  (1) 動いているトキワを止める
rem ============================================================
echo [1/3] 動いているトキワを止めています...
taskkill /F /T /FI "WINDOWTITLE eq トキワ 起動ランチャー*" >nul 2>nul
taskkill /F /T /FI "WINDOWTITLE eq トキワ 店内共有で起動" >nul 2>nul
taskkill /F /T /FI "WINDOWTITLE eq トキワ サーバー*" >nul 2>nul
where powershell >nul 2>nul && powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*server*app.py*' } | ForEach-Object { taskkill /F /T /PID $_.ProcessId }" >nul 2>nul
timeout /t 1 /nobreak >nul
echo       止めました。
echo.

rem ============================================================
rem  (2) 最新版を取り込む
rem ============================================================
echo [2/3] 最新版を取り込んでいます...
set "UPDATED=no"
set "UPDMSG="

where git >nul 2>nul
if errorlevel 1 (
  set "UPDMSG=git が見つからないため、更新できませんでした。"
  goto AFTERPULL
)

rem ---- ★前回の更新が途中で止まっていないか先に見る ----
rem   ここが残っていると git pull は何度やっても必ず失敗する。
rem   英語のエラーを繰り返しても意味がないので、日本語で説明して更新を飛ばす。
if exist ".git\rebase-merge" goto CONFLICTED
if exist ".git\rebase-apply" goto CONFLICTED
if exist ".git\MERGE_HEAD" goto CONFLICTED

rem ---- 今いるブランチを調べる ----
set "BR="
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "BR=%%b"
if not defined BR (
  set "UPDMSG=このフォルダは git の管理下ではないため、更新できませんでした。"
  goto AFTERPULL
)

set RETRY=0
:PULL
git pull origin !BR!
if not errorlevel 1 goto PULLED
set /a RETRY+=1
if !RETRY! GEQ 3 goto PULLFAIL
set /a "WAIT=RETRY*2"
echo.
echo   取り込みに失敗しました。!WAIT!秒待ってもう一度試します（!RETRY!/2回目）...
timeout /t !WAIT! /nobreak >nul
goto PULL

:PULLED
set "UPDATED=yes"
echo       取り込みました。
goto AFTERPULL

:PULLFAIL
rem ---- 2回試して駄目。ぶつかっている(衝突)のか、通信の問題かを見分ける ----
if exist ".git\rebase-merge" goto CONFLICTED
if exist ".git\rebase-apply" goto CONFLICTED
if exist ".git\MERGE_HEAD" goto CONFLICTED
set "UPDMSG=最新版を取り込めませんでした（ネットにつながっているか確認してください）。"
goto AFTERPULL

:CONFLICTED
echo.
echo ============================================
echo  [お知らせ] 更新がぶつかって止まっています
echo ============================================
echo.
echo  このPCで直接変更したものと、新しい版が同じファイルを触っています。
echo  このままでは何度やっても更新できません。
echo.
echo  ★今日の営業には影響しません。このあと今のまま起動します。
echo.
echo  直し方: この画面の内容を写真に撮って送ってください。
echo          （元に戻すコマンドをお伝えします）
echo.
set "UPDMSG=更新がぶつかっているため、今のままの版で起動します。"
goto AFTERPULL

:AFTERPULL
echo.

rem ============================================================
rem  (3) 本番運用で起動
rem ============================================================
if not exist "db\tokiwa.db" goto NODB

echo [3/3] トキワを起動しています...

rem ---- クロネコB2の書き出しに必要な部品の確認(無くても起動はします)----
%PY% -c "import openpyxl" >nul 2>nul
if not errorlevel 1 goto XLOK
echo.
echo  [お知らせ] クロネコB2の書き出しに必要な部品 openpyxl が入っていません。
echo             DM便の書き出しを使う時は、次を一度だけ実行してください:
echo               %PY% -m pip install openpyxl
echo.
:XLOK

rem ---- サーバーを起動(lan=店内共有 / kiki=機器ON)。黒い画面は出さない ----
start "" %PYW% server\app.py lan kiki

rem ---- ★本当に起動したかを確認する(画面を隠すので、失敗に気づけるように)----
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
timeout /t 3 /nobreak >nul

:STARTED
rem ---- 更新後のバージョンを出す(pull が効いたかが一目で分かる)----
set "VERAFTER="
for /f "tokens=2 delims==" %%v in ('findstr /c:"var TOKIWA_VERSION" tokiwa-ui.html 2^>nul') do set "VERAFTER=%%v"
echo.
echo ============================================
if "!UPDATED!"=="yes" (
  echo   更新して起動しました
) else (
  echo   起動しました（★更新はできていません）
)
echo ============================================
if defined VERAFTER echo   バージョン: !VERAFTER!
if not "!UPDMSG!"=="" echo   ※ !UPDMSG!
echo.
echo   ブラウザを開きます。止める時は トキワ停止.bat を使ってください。
start "" "http://localhost:8760/"
if not "!UPDMSG!"=="" (
  echo.
  echo   ★上のお知らせを読んでから閉じてください。
  pause
)
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
echo   ・既にトキワが動いている
echo   ・db\tokiwa.db が壊れている
echo   ・Python の部品が足りない
echo.
echo  画面を出して原因を見るには「ツール\別の起動のしかた\機器ありで起動.bat」で
echo  起動してください。黒い画面にエラーがそのまま表示されます。
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
echo   ※お試しで動かしたいだけなら「ツール\別の起動のしかた\トキワ起動.bat」を使ってください。
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
echo   2) インストール後、このバッチをもう一度実行してください。
echo.
pause
endlocal
exit /b 1
