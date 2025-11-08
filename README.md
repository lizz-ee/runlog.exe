# 🎨 Scian

> **Turn creative chaos into visual clarity.**

The AI social planner that learns your style, writes your captions, and keeps your feed on-story.

## 🏗️ Architecture

```
scian/
├── backend/          # Python FastAPI (AI processing, APIs)
└── frontend/         # Electron + React (UI, panels)
```

## ✨ Core Features

- **Visual Brain**: AI tags your photos & videos by color, tone, and emotion
- **Nuke-Style Panels**: Draggable, dockable workspace modules
- **AI Captioner**: Auto-generates authentic captions that sound like you
- **Feed Planner**: Drag, drop, and preview your next posts
- **Complete Social Media Management**: Multi-platform scheduling, analytics, engagement

## 🎨 Design Philosophy

**Clean, modern aesthetic** (professional, cinematic, minimal)
+ **Nuke-style panels** (flexible, powerful workspace)
+ **Complete social media management** (scheduling, analytics, AI-powered)

## 🚀 Quick Start

### Backend (Python)
```bash
cd backend
pip install -r requirements.txt
python run.py
# API runs at http://localhost:8000
```

### Frontend (Electron + React)
```bash
cd frontend
npm install
npm run dev
# App opens automatically
```

## 🛠️ Tech Stack

**Backend:**
- Python 3.11+
- FastAPI (REST API)
- SQLAlchemy (Database ORM)
- Anthropic Claude (AI)
- OpenCV (Image analysis)
- FFmpeg (Video processing)

**Frontend:**
- Electron (Desktop wrapper)
- React 19 + TypeScript
- Vite (Build tool)
- Tailwind CSS (Styling)
- react-mosaic (Nuke-style panels)
- Zustand (State management)

## 📦 Deployment Path

1. **Desktop**: Electron app (Windows, Mac, Linux)
2. **Web**: React app deployed to Vercel/Netlify
3. **Mobile**: React Native (reuses frontend components)
