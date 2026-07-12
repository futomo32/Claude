@echo off
setlocal
cd /d "%~dp0"
title トキワ 店内共有で起動

echo ============================================
echo   トキワ を店内共有モードで起動します
echo ============================================
echo.
echo  ・同じネットワークの他のPCからもブラウザで使えます
echo  ・他のPCは「閲覧・顧客登録・商品登録」のみ（レジは本体のみ）
echo  ・初回はWindowsファイアウォールの確認が出たら
echo    「アクセスを許可する」を押してください
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY (
  echo [エラー] Python が見つかりませんでした。トキワ起動.bat の案内を参照してください。
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
