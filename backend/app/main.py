from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from .database import engine, Base
from .api import api_router
from .config import settings

# Create all tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Marathon RunLog",
    description="Track your Marathon extraction runs with screenshot parsing",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded screenshots
os.makedirs(settings.media_upload_dir, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.media_upload_dir), name="media")

app.include_router(api_router)


@app.get("/")
def root():
    return {"app": "Marathon RunLog", "version": "1.0.0", "status": "running"}
