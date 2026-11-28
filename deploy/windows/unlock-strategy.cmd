@echo off
rem Owner only: lifts the safety lock on the adaptive strategy so it may trade where execution is on (demo).
rem Asks the owner's app password. Real-money trading is a separate switch and stays off.
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m gold_ai --config config.local.json unlock-strategy
pause
