import uvicorn
import os

if __name__ == "__main__":
    is_dev = os.environ.get("RUNLOG_DEV", "0") == "1"
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=is_dev,
    )
