@echo off
chcp 936 >nul
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

rem 用法：双击运行，或 start.bat 8001 指定端口
set "PORT=%~1"
if not defined PORT set "PORT=8000"
set "URL=http://127.0.0.1:%PORT%"
title Vagent - %URL%

if not exist "vagent_app.py" (
  echo [x] 没找到 vagent_app.py，请把本脚本放在项目根目录。
  pause
  exit /b 1
)

call :probe
if not errorlevel 1 (
  echo [i] Vagent 已经在运行：%URL%
  if not defined VAGENT_NO_BROWSER start "" "%URL%"
  ping -n 2 127.0.0.1 >nul
  exit /b 0
)

call :find_python
if not defined PY (
  echo [x] 没有找到装了 Flask 的 Python。
  echo     先执行：python -m pip install -r requirements.txt
  echo     或安装 Python 3.12 后重试。
  echo.
  pause
  exit /b 1
)

echo [i] Python : %PY%
echo [i] 服务   : %URL%
echo [i] 停止服务：在 Vagent 窗口里按 Ctrl+C，或直接关闭那个窗口。
echo.

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
start "Vagent %PORT%" cmd /k ""%PY%" vagent_app.py --port %PORT%"

set /a tries=0
:wait
call :probe
if not errorlevel 1 goto ready
set /a tries+=1
if !tries! geq 30 (
  echo [x] 等了 30 秒服务还没起来，请查看 Vagent 窗口里的报错。
  pause
  exit /b 1
)
ping -n 2 127.0.0.1 >nul
goto wait

:ready
echo [i] 启动完成。
if not defined VAGENT_NO_BROWSER (
  start "" "%URL%"
  echo [i] 已打开浏览器；这个启动窗口可以关闭。
) else (
  echo [i] 已跳过打开浏览器（VAGENT_NO_BROWSER=1）。
)
ping -n 4 127.0.0.1 >nul
exit /b 0

:probe
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri '%URL%/api/bootstrap' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {} ; exit 1" >nul 2>&1
exit /b %errorlevel%

:find_python
set "PY="
for /f "delims=" %%p in ('py -3.12 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%p"
if defined PY (
  "%PY%" -c "import flask" >nul 2>&1 || set "PY="
)
if not defined PY (
  for /f "delims=" %%p in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%p"
  if defined PY (
    "%PY%" -c "import flask" >nul 2>&1 || set "PY="
  )
)
if not defined PY (
  for %%p in (
    "%USERPROFILE%\anaconda3\python.exe"
    "C:\ProgramData\anaconda3\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  ) do (
    if exist "%%~p" (
      "%%~p" -c "import flask" >nul 2>&1 && set "PY=%%~p"
    )
  )
)
exit /b 0