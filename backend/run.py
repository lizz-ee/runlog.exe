import uvicorn
import os

# Prevent cp1252 crashes from EasyOCR progress bars on Windows
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def _get_api_port() -> int:
    try:
        port = int(os.environ.get("RUNLOG_API_PORT", "8000"))
    except ValueError:
        port = 8000
    return port if 1 <= port <= 65535 else 8000


if __name__ == "__main__":
    is_dev = os.environ.get("RUNLOG_DEV", "0") == "1"
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=_get_api_port(),
        reload=is_dev,
    )
