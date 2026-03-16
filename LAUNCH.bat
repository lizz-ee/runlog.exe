@echo off
echo === Marathon RunLog ===
echo.
echo Starting backend...
start "RunLog Backend" cmd /k "cd backend && python run.py"
echo.
echo Starting frontend...
cd frontend
start "RunLog Frontend" cmd /k "npm run dev"
echo.
echo Backend: http://localhost:8000
echo Frontend: http://localhost:5173
echo API Docs: http://localhost:8000/docs
echo.
pause
