@echo off
setlocal enabledelayedexpansion
title runlog.exe - Installer
color 0A

echo.
echo  ========================================================
echo                  runlog.exe - INSTALLER
echo.
echo    Local-first Marathon companion
echo    AI-powered stats, narratives, highlight clips
echo  ========================================================
echo.

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "RECORDER=%BACKEND%\recorder"
set "TOOLS=%BACKEND%\tools"
set ERRORS=0

:: ===========================================================
:: PHASE 1: CHECK PREREQUISITES
:: ===========================================================

echo  [PHASE 1] Checking prerequisites...
echo  --------------------------------------------------------
echo.

:: --- Python 3.12+ ---
echo  [1/4] Python 3.12+ ...
set "PYTHON_CMD="
:: Check common install locations first (most reliable)
for %%V in (314 313 312) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
        set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python%%V\;%LOCALAPPDATA%\Programs\Python\Python%%V\Scripts\;%PATH%"
        goto :python_found
    )
)
:: Check system-wide installs
for %%V in (314 313 312) do (
    if exist "C:\Python%%V\python.exe" (
        set "PYTHON_CMD=C:\Python%%V\python.exe"
        set "PATH=C:\Python%%V\;C:\Python%%V\Scripts\;%PATH%"
        goto :python_found
    )
)
:: Check PATH as last resort (but verify it's real Python, not Windows Store alias)
python -m pip --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python"
    goto :python_found
)
:: Not found anywhere - install
echo        NOT FOUND - Installing Python...
echo        Downloading Python 3.12 installer...
powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile '%TEMP%\python-installer.exe'" 2>nul
if not exist "%TEMP%\python-installer.exe" (
    echo        ERROR: Failed to download Python. Please install manually from python.org
    set /a ERRORS+=1
    goto :check_node
)
echo        Launching Python installer...
echo        IMPORTANT: Check "Add python.exe to PATH" at the bottom of the installer!
echo        Click "Install Now" and wait for it to finish.
echo.
start /wait "" "%TEMP%\python-installer.exe" PrependPath=1 Include_pip=1
del "%TEMP%\python-installer.exe" 2>nul
:: Check if it installed
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312\;%LOCALAPPDATA%\Programs\Python\Python312\Scripts\;%PATH%"
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto :python_found
)
echo        ERROR: Python install failed. Please install manually from python.org
set /a ERRORS+=1
goto :check_node

:python_found
:: Resolve to full absolute path so the app can find it later
echo import sys; print(sys.executable)> "%TEMP%\_pypath.py"
for /f "delims=" %%P in ('"%PYTHON_CMD%" "%TEMP%\_pypath.py"') do set "PYTHON_CMD=%%P"
del "%TEMP%\_pypath.py" 2>nul
for /f "tokens=2" %%v in ('"%PYTHON_CMD%" --version 2^>^&1') do echo        FOUND: Python %%v

:check_node
:: --- Node.js 18+ ---
echo  [2/4] Node.js 18+ ...
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo        NOT FOUND - Installing Node.js...
    echo        Downloading Node.js LTS installer...
    powershell -Command "Invoke-WebRequest -Uri 'https://nodejs.org/dist/v22.14.0/node-v22.14.0-x64.msi' -OutFile '%TEMP%\node-installer.msi'" 2>nul
    if not exist "%TEMP%\node-installer.msi" (
        echo        ERROR: Failed to download Node.js. Please install manually from nodejs.org
        set /a ERRORS+=1
        goto :check_ffmpeg
    )
    echo        Launching Node.js installer...
    echo        Click through the installer and wait for it to finish.
    start /wait "" msiexec /i "%TEMP%\node-installer.msi" /norestart
    del "%TEMP%\node-installer.msi" 2>nul
    :: Refresh PATH for both common install locations
    set "PATH=C:\Program Files\nodejs\;%LOCALAPPDATA%\Programs\nodejs\;%PATH%"
)
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo        ERROR: Node.js still not found after install. Restart terminal and try again.
    set /a ERRORS+=1
) else (
    for /f %%v in ('node --version 2^>^&1') do echo        FOUND: Node.js %%v
)

:check_ffmpeg
:: --- FFmpeg ---
echo  [3/4] FFmpeg ...
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    :: Check if we already downloaded it locally
    if exist "%TOOLS%\ffmpeg\bin\ffmpeg.exe" (
        set "PATH=%TOOLS%\ffmpeg\bin;%PATH%"
        echo        FOUND: Local FFmpeg
    ) else (
        echo        NOT FOUND - Downloading FFmpeg...
        if not exist "%TOOLS%" mkdir "%TOOLS%"
        powershell -Command "Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile '%TEMP%\ffmpeg.zip'" 2>nul
        if not exist "%TEMP%\ffmpeg.zip" (
            echo        ERROR: Failed to download FFmpeg. Please install manually and add to PATH.
            set /a ERRORS+=1
            goto :check_rust
        )
        echo        Extracting...
        powershell -Command "Expand-Archive -Path '%TEMP%\ffmpeg.zip' -DestinationPath '%TEMP%\ffmpeg-extract' -Force" 2>nul
        :: Move the inner folder to tools/ffmpeg
        for /d %%d in ("%TEMP%\ffmpeg-extract\ffmpeg-*") do (
            xcopy "%%d\bin\*" "%TOOLS%\ffmpeg\bin\" /E /I /Y >nul 2>&1
        )
        del "%TEMP%\ffmpeg.zip" 2>nul
        rmdir /s /q "%TEMP%\ffmpeg-extract" 2>nul
        set "PATH=%TOOLS%\ffmpeg\bin;%PATH%"
    )
)
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    if exist "%TOOLS%\ffmpeg\bin\ffmpeg.exe" (
        echo        FOUND: Local FFmpeg
    ) else (
        echo        ERROR: FFmpeg not available.
        set /a ERRORS+=1
    )
) else (
    echo        FOUND: FFmpeg
)

:check_rust
:: --- Rust ---
echo  [4/4] Rust toolchain ...
cargo --version >nul 2>&1
if %errorlevel% neq 0 (
    :: Check common install location
    if exist "%USERPROFILE%\.cargo\bin\cargo.exe" (
        set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
    ) else (
        echo        NOT FOUND - Installing Rust...
        echo        Downloading rustup...
        powershell -Command "Invoke-WebRequest -Uri 'https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe' -OutFile '%TEMP%\rustup-init.exe'" 2>nul
        if not exist "%TEMP%\rustup-init.exe" (
            echo        ERROR: Failed to download Rust. Please install manually from rustup.rs
            set /a ERRORS+=1
            goto :phase2
        )
        echo        Running installer...
        "%TEMP%\rustup-init.exe" -y --default-toolchain stable >nul 2>&1
        del "%TEMP%\rustup-init.exe" 2>nul
        set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
    )
)
cargo --version >nul 2>&1
if %errorlevel% neq 0 (
    echo        ERROR: Rust still not found. Restart terminal and try again.
    set /a ERRORS+=1
) else (
    for /f "tokens=1,2" %%a in ('cargo --version 2^>^&1') do echo        FOUND: %%a %%b
)

:phase2
echo.
if %ERRORS% gtr 0 (
    echo  [!] %ERRORS% prerequisite[s] failed. Fix the errors above and run install.bat again.
    echo.
    pause
    exit /b 1
)
echo  All prerequisites found.
echo.

:: ===========================================================
:: PHASE 2: INSTALL DEPENDENCIES
:: ===========================================================

echo  [PHASE 2] Installing dependencies...
echo  --------------------------------------------------------
echo.

:: --- Python deps ---
echo  [1/3] Python packages [this may take a few minutes]...
cd /d "%BACKEND%"
:: Ensure pip is available (some installs miss it)
"%PYTHON_CMD%" -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo        Bootstrapping pip...
    powershell -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%TEMP%\get-pip.py'" 2>nul
    "%PYTHON_CMD%" "%TEMP%\get-pip.py" --quiet >nul 2>&1
    del "%TEMP%\get-pip.py" 2>nul
)
echo        Installing PyTorch [CPU-only]...
"%PYTHON_CMD%" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu --quiet >nul 2>&1
if %errorlevel% neq 0 (
    echo        ERROR: PyTorch install failed.
    set /a ERRORS+=1
)
echo        Installing requirements...
"%PYTHON_CMD%" -m pip install -r requirements.txt --quiet >nul 2>&1
if %errorlevel% neq 0 (
    echo        ERROR: Requirements install failed.
    set /a ERRORS+=1
)
echo        Downloading OCR models [first-time only]...
"%PYTHON_CMD%" -c "import easyocr; easyocr.Reader(['en'], gpu=False)" >nul 2>&1
echo        Python packages installed.

:: --- Rust recorder ---
echo  [2/3] Building Rust recorder...
cd /d "%RECORDER%"
cargo build --release 2>&1
if exist "%RECORDER%\target\release\runlog-recorder.exe" (
    echo        Recorder built successfully.
) else (
    echo        ERROR: Recorder build failed.
    set /a ERRORS+=1
)

:: --- Node.js deps ---
echo  [3/3] Node.js packages...
cd /d "%FRONTEND%"
call npm install --loglevel=error 2>&1
if %errorlevel% equ 0 (
    echo        Node packages installed.
) else (
    echo        ERROR: npm install failed.
    set /a ERRORS+=1
)

echo.

:: ===========================================================
:: PHASE 3: BUILD
:: ===========================================================

echo  [PHASE 3] Building application...
echo  --------------------------------------------------------
echo.

cd /d "%FRONTEND%"
:: Skip code signing (no certificate)
set CSC_IDENTITY_AUTO_DISCOVERY=false
echo  Building frontend + packaging installer...
call npm run dist 2>&1
if exist "%ROOT%release\win-unpacked\runlog.exe" (
    echo.
    echo  Build complete.
    :: Embed icon into exe (electron-builder's rcedit often fails on non-admin Windows)
    if not exist "%TOOLS%\rcedit-x64.exe" (
        echo  Downloading rcedit...
        powershell -Command "Invoke-WebRequest -Uri 'https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe' -OutFile '%TOOLS%\rcedit-x64.exe'" 2>nul
    )
    if exist "%TOOLS%\rcedit-x64.exe" (
        "%TOOLS%\rcedit-x64.exe" "%ROOT%release\win-unpacked\runlog.exe" --set-icon "%FRONTEND%\electron\icon.ico" 2>nul
        echo  Icon embedded.
    )
) else (
    echo.
    echo  ERROR: Build failed. Check output above.
    set /a ERRORS+=1
)

:: ===========================================================
:: PHASE 4: SAVE PYTHON PATH
:: ===========================================================

:: Save the resolved Python path so the app can find it at runtime
:: (Electron packaged apps often don't inherit the user's full PATH)
set "RUNLOG_CFG=%APPDATA%\runlog"
if not exist "%RUNLOG_CFG%" mkdir "%RUNLOG_CFG%"
echo %PYTHON_CMD%> "%RUNLOG_CFG%\python-path"
echo  Python path saved: %PYTHON_CMD%

:: ===========================================================
:: PHASE 5: CREATE SHORTCUT
:: ===========================================================

:: Create a shortcut to runlog.exe in the repo root for easy access
if exist "%ROOT%release\win-unpacked\runlog.exe" (
    echo  Creating shortcut...
    powershell -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('%ROOT%runlog.exe.lnk'); $sc.TargetPath = '%ROOT%release\win-unpacked\runlog.exe'; $sc.WorkingDirectory = '%ROOT%release\win-unpacked'; $sc.Description = 'runlog.exe - Marathon Companion'; $sc.Save()" 2>nul
    if exist "%ROOT%runlog.exe.lnk" (
        echo  Shortcut created: runlog.exe
    )
)

:: ===========================================================
:: DONE
:: ===========================================================

echo.
echo  ========================================================
if %ERRORS% gtr 0 (
    echo  INSTALL COMPLETED WITH %ERRORS% ERROR[S]
    echo  Check the output above for details.
) else (
    echo  INSTALL COMPLETE
    echo.
    echo  Double-click runlog.lnk to launch the app.
    echo.
    echo  Or run directly from source:
    echo    Terminal 1:  cd backend ^& python run.py
    echo    Terminal 2:  cd frontend ^& npm run electron:dev
)
echo  ========================================================
echo.
pause
