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
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo        NOT FOUND - Installing Python...
    echo        Downloading Python 3.12 installer...
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile '%TEMP%\python-installer.exe'" 2>nul
    if not exist "%TEMP%\python-installer.exe" (
        echo        ERROR: Failed to download Python. Please install manually from python.org
        set /a ERRORS+=1
        goto :check_node
    )
    echo        Running installer [this may take a minute]...
    "%TEMP%\python-installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
    del "%TEMP%\python-installer.exe" 2>nul
    :: Refresh PATH
    set "PATH=%LOCALAPPDATA%\Programs\Python\Python312\;%LOCALAPPDATA%\Programs\Python\Python312\Scripts\;%PATH%"
)
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo        ERROR: Python still not found after install. Restart terminal and try again.
    set /a ERRORS+=1
) else (
    for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo        FOUND: Python %%v
)

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
    echo        Running installer...
    msiexec /i "%TEMP%\node-installer.msi" /quiet /norestart
    del "%TEMP%\node-installer.msi" 2>nul
    :: Refresh PATH
    set "PATH=C:\Program Files\nodejs\;%PATH%"
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
    echo  [!] %ERRORS% prerequisite[s] failed. Fix the errors above and run install_runlog.bat again.
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
echo        Installing PyTorch [CPU-only]...
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu --quiet 2>&1 | findstr /i "error" && set /a ERRORS+=1
echo        Installing requirements...
pip install -r requirements.txt --quiet 2>&1 | findstr /i "error" && set /a ERRORS+=1
if %ERRORS% equ 0 (
    echo        Python packages installed.
) else (
    echo        WARNING: Some packages may have failed. Check output above.
)

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
echo  Building frontend + packaging installer...
call npm run dist 2>&1
if exist "%ROOT%release\runlog Setup 1.0.0.exe" (
    echo.
    echo  Build complete.
) else (
    echo.
    echo  ERROR: Build failed. Check output above.
    set /a ERRORS+=1
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
    echo  Installer:  release\runlog Setup 1.0.0.exe
    echo  Run it to install runlog.exe to your system.
    echo.
    echo  Or run directly from source:
    echo    Terminal 1:  cd backend ^& python run.py
    echo    Terminal 2:  cd frontend ^& npm run electron:dev
)
echo  ========================================================
echo.
pause
