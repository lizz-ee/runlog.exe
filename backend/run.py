import uvicorn
import os

# Prevent cp1252 crashes from EasyOCR progress bars on Windows
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

if __name__ == "__main__":
    is_dev = os.environ.get("RUNLOG_DEV", "0") == "1"
    port = int(os.environ.get("RUNLOG_PORT", "8000"))
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        reload=is_dev,
    )
