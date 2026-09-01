@echo off
setlocal enabledelayedexpansion
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
rem   ".." が1つだと ツール\ 止まりで server\ や db\ を見失う(2026-09-01 修正)
cd /d "%~dp0..\.."
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
if not defined PY goto NOPYTHON

rem ---- 本物の Python か確認（バージョンを表示できれば本物）----
echo 使用する Python: %PY%
%PY% --version
if errorlevel 1 goto NOPYTHON
echo.

rem ---- DB が無ければサンプルを作成（既にあれば残す）----
if not exist "db\tokiwa.db" (
  echo サンプルDBを作成します（初回のみ）...
  %PY% scripts\make_sample_data.py
  if errorlevel 1 (
    echo.
    echo [エラー] サンプルDBの作成に失敗しました。上の内容を確認してください。
    echo.
    pause
    exit /b 1
  )
) else (
  echo 既存のDB（db\tokiwa.db）を使用します。作り直す時はこのファイルを削除してください。
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
echo  起動しました。終了するには
echo  「トキワ サーバー」ウィンドウを閉じてください。
echo --------------------------------------------
echo.
pause
endlocal
exit /b 0

:NOPYTHON
echo.
echo [エラー] 使用できる Python が見つかりませんでした。
echo   ※「使用する Python: python」と出ていても、実際は Windows ストアの
echo      ダミーのショートカットだけの場合があります（本物ではありません）。
echo.
echo   対処:
echo   1) https://www.python.org/downloads/windows/ から Python をインストール
echo      インストーラの最初の画面で
echo      「Add python.exe to PATH」に必ずチェックを入れてください。
echo   2) インストール後、この「ツール\別の起動のしかた\トキワ起動.bat」をもう一度ダブルクリック
echo.
echo   （Python 無しで画面だけ確認したい場合は tokiwa-ui.html をダブルクリック）
echo.
pause
endlocal
exit /b 1
