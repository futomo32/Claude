@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
title トキワ 起動ランチャー

echo ============================================
echo   トキワ 宝飾店管理システム を起動します
echo ============================================
echo.
echo  ・このランチャーは localhost（このPC内）だけで動きます
echo  ・宝飾ナビは開いたままで問題ありません（閉じる必要なし）
echo  ・プリンター/ドロワー/カードリーダーは操作しません
echo.

rem ---- Python を探す（py 優先、無ければ python / python3）----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY (
  echo [エラー] Python が見つかりませんでした。
  echo   https://www.python.org/ からインストールし、
  echo   インストール時に「Add python.exe to PATH」に必ずチェックしてください。
  echo   ※ Python 無しで画面だけ見たい場合は tokiwa-ui.html をダブルクリックしてください。
  echo.
  pause
  exit /b 1
)
echo 使用する Python: %PY%
echo.

rem ---- DB が無ければサンプルを作成（既にあれば残す＝テストデータを消さない）----
if not exist "db\tokiwa.db" (
  echo サンプルDBを作成します（初回のみ）...
  %PY% scripts\make_sample_data.py
  if errorlevel 1 (
    echo [エラー] サンプルDBの作成に失敗しました。上のメッセージを確認してください。
    echo.
    pause
    exit /b 1
  )
) else (
  echo 既存のDB（db\tokiwa.db）を使用します。作り直したい時はこのファイルを削除してください。
)
echo.

rem ---- サーバーを別ウィンドウで起動 ----
echo トキワサーバーを起動します...
start "トキワ サーバー（このウィンドウを閉じると停止します）" %PY% server\app.py

rem ---- サーバーの立ち上がりを少し待ってからブラウザを開く ----
timeout /t 3 >nul
echo ブラウザを開きます: http://localhost:8760/
start "" "http://localhost:8760/"

echo.
echo --------------------------------------------
echo  起動しました。
echo  ・使うとき   : 開いたブラウザで操作してください
echo  ・終了するとき: 「トキワ サーバー」ウィンドウを閉じてください
echo --------------------------------------------
echo.
pause
endlocal
