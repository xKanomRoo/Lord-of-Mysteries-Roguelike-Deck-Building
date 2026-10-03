@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto python_fallback
py -3 "%~dp0export_all_game_resources_windows.py"
set "CZN_EXIT=%ERRORLEVEL%"
goto finish
:python_fallback
where python >nul 2>nul
if errorlevel 1 goto no_python
python "%~dp0export_all_game_resources_windows.py"
set "CZN_EXIT=%ERRORLEVEL%"
goto finish
:no_python
echo ไม่พบ Python กรุณาติดตั้ง Python 3.12 ขึ้นไปแล้วเปิดไฟล์นี้อีกครั้ง
set "CZN_EXIT=1"
:finish
echo.
echo เก็บข้อความในหน้าต่างนี้ไว้หากโปรแกรมแจ้งข้อผิดพลาด
pause
exit /b %CZN_EXIT%
