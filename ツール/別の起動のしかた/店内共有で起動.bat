@echo off
setlocal
rem ★このバッチは ツール\分類\ の下(2階層)にあるので、トキワ本体のフォルダ(2つ上)へ移動してから動く。
rem   ".." が1つだと ツール\ 止まりで server\ や db\ を見失う(2026-09-01 修正)
cd /d "%~dp0..\.."
title トキワ 店内共有で起動

echo ============================================
echo   トキワ を店内共有モードで起動します
echo ============================================
echo.
echo  ・同じネットワークの他のPC・スマホ・iPadからもブラウザで使えます
echo  ・各端末でログインが必要です。使える範囲は権限(管理者/社員/パート)で決まります
echo  ・初回はWindowsファイアウォールの確認が出たら
echo    「アクセスを許可する」を押してください
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY (
  echo [エラー] Python が見つかりませんでした。同じフォルダの トキワ起動.bat の案内を参照してください。
  pause
  exit /b 1
)
%PY% --version
if errorlevel 1 (
  echo [エラー] Python が正しく動きません。
  pause
  exit /b 1
)

if not exist "db\tokiwa.db" (
  echo サンプルDBを作成します（初回のみ）...
  %PY% scripts\make_sample_data.py
  if errorlevel 1 (
    echo [エラー] サンプルDBの作成に失敗しました。
    pause
    exit /b 1
  )
)

start "トキワ サーバー（店内共有・このウィンドウを閉じると停止）" %PY% server\app.py lan
timeout /t 3 >nul
start "" "http://localhost:8760/"
echo.
echo 起動しました。他のPCで開くURLは「トキワ サーバー」ウィンドウに表示されています。
echo 終了するには「トキワ サーバー」ウィンドウを閉じてください。
echo.
pause
endlocal
