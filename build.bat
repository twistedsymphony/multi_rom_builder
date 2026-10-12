@echo off
REM Builds dist\MultiBuilder.exe  (needs Python 3.10+ from python.org and git)
git submodule update --init
py -m pip install -r requirements.txt
py -m PyInstaller --noconfirm MultiBuilder.spec
PAUSE
