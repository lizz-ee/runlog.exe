"""
Scian Backend - FastAPI Server
Entry point for the application
"""

import uvicorn
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

if __name__ == "__main__":
    host = os.getenv("API_HOST", "localhost")
    port = int(os.getenv("API_PORT", "8000"))
    debug = os.getenv("DEBUG", "True").lower() == "true"

    print(f"""
    Scian Backend Starting...

    API: http://{host}:{port}
    Docs: http://{host}:{port}/docs
    Debug: {debug}
    """)

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=debug,
        log_level="info"
    )
