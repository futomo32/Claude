@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title トキワ ロゴなしで起動（店名表示テスト）

echo ============================================
echo   トキワ ロゴなしで起動（店名表示テスト）
echo ============================================
echo.
echo  ・ロゴ画像を配信しないモードで起動します（画像ファイルには一切触りません）
echo  ・帳票（見積書・請求書）のヘッダが正式店名の文字になることを確認できます
echo  ・確認方法: 見積・請求画面 → 請求書のプレビュー → ヘッダが
echo    「宝石・メガネ・時計 ヤナセ」の文字になっていればOK
echo  ・表示テスト専用です。確認が終わったら閉じて、通常の「トキワ起動.bat」を使ってください
echo.

rem ---- Python を探す（py 優先、無ければ python / python3）----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY goto NOPYTHON

if not exist "db\tokiwa.db" (
  echo [エラー] db\tokiwa.db がありません。先に「トキワ起動.bat」で作成してください。
  goto END
)

rem ---- サーバーを別ウィンドウで起動（ロゴなしモード）----
echo トキワサーバーを起動します（ロゴなしモード）...
start "トキワ サーバー・ロゴなしテスト（このウィンドウを閉じると停止します）" %PY% server\app.py nologo

rem ---- サーバーの立ち上がりを少し待ってからブラウザを開く ----
timeout /t 3 >nul
echo ブラウザを開きます: http://localhost:8760/
start "" "http://localhost:8760/"

echo.
echo --------------------------------------------
echo  起動しました。確認が終わったら
echo  「トキワ サーバー・ロゴなしテスト」ウィンドウを閉じてください。
echo --------------------------------------------
goto END

:NOPYTHON
echo.
echo [エラー] Python が見つかりません。
echo   python.org 版をインストールし「Add python.exe to PATH」にチェックしてください。
goto END

:END
echo.
pause
