@echo off
chcp 65001 >nul
title WH40K 场景摄影棚服务器 (端口 8943)
cd /d "%~dp0"
echo ============================================
echo   WH40K 场景摄影棚 - 本地模式
echo   资产从硬盘直读（无需下载），布局每 10 秒
echo   自动备份到 layouts\backup.json
echo   浏览器将自动打开: http://localhost:8943
echo   关闭本窗口即停止服务
echo ============================================
rem 2 秒后自动打开浏览器（给服务器留启动时间）；若端口已有服务在跑，python 会报错退出，浏览器照常可用
start "" /b cmd /c "timeout /t 2 /nobreak >nul & start "" http://localhost:8943"
python serve.py
if errorlevel 1 (
  echo.
  echo 服务器未能启动。常见原因：
  echo   1. 端口 8943 已被占用（已有摄影棚在跑——浏览器页面照常可用，无需处理）
  echo   2. 未安装 Python 或不在 PATH 中
  pause
)
