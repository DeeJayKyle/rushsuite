@echo off
setlocal EnableDelayedExpansion
title RushSuite build
cd /d "%~dp0"
echo.
echo  Building RushSuite... downloads ~5 GB once and takes 20-60 minutes.
echo  Options:  build.bat clone    (add "clone your voice", ~3 GB extra)
echo            build.bat nollm    (skip the offline AI model; use a free online key instead)
echo.
set ARGS=
for %%A in (%*) do (
  if /I "%%A"=="clone"  set ARGS=!ARGS! -Clone
  if /I "%%A"=="nollm"  set ARGS=!ARGS! -NoLLM
  if /I "%%A"=="notest" set ARGS=!ARGS! -NoSelfTest
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" !ARGS!
echo.
pause
