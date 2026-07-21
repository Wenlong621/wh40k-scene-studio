@echo off
chcp 65001 >nul
title WH40K 场景摄影棚服务器 (端口 8943)
cd /d "%~dp0"
echo ============================================
echo   WH40K 场景摄影棚 - 本地服务器
echo   浏览器打开: http://localhost:8943
echo   关闭本窗口即停止服务
echo ============================================
python serve.py
if errorlevel 1 (
  echo.
  echo 启动失败。常见原因：
  echo   1. 端口 8943 已被占用（可能 Claude 会话的托管服务正在跑，那就直接用它）
  echo   2. 未安装 Python 或不在 PATH 中
  pause
)
