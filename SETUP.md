# 🚀 Scian - Setup Guide

## Prerequisites

- **Python 3.11+** (for backend)
- **Node.js 18+** (for frontend)
- **npm or yarn** (package manager)

## 🎯 Quick Start

### 1. Backend Setup

```bash
cd backend

# Create virtual environment (recommended)
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
copy .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Run the backend
python run.py
```

Backend will start at: **http://localhost:8000**
API docs at: **http://localhost:8000/docs**

### 2. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

Frontend will start at: **http://localhost:5173**
Electron app will launch automatically!

## 🎨 Features

- ✅ **Nuke-style panel system** - Drag, drop, dock panels anywhere
- ✅ **AI Assistant** - Powered by Claude for captions and suggestions
- ✅ **Media Library** - Visual grid for your creative assets
- ✅ **Post Editor** - Multi-platform content creation
- ✅ **Calendar** - Visual content planning
- ✅ **Analytics** - Track your performance

## 🔧 Development Workflow

### Backend Development
```bash
cd backend
python run.py
# Hot reload enabled - changes reflect automatically
```

### Frontend Development
```bash
cd frontend
npm run dev
# Vite hot reload + Electron auto-restart
```

### Building for Production

**Backend:**
```bash
cd backend
# Backend runs as a service, no build needed
# For deployment, use Docker or systemd
```

**Frontend (Electron App):**
```bash
cd frontend
npm run build:electron
# Output: frontend/dist-electron/
```

## 📁 Project Structure

```
scian/
├── backend/
│   ├── app/
│   │   ├── api/          # API endpoints
│   │   ├── core/         # Business logic
│   │   └── main.py       # FastAPI app
│   ├── requirements.txt
│   └── run.py
│
├── frontend/
│   ├── electron/         # Electron main process
│   ├── src/
│   │   ├── components/   # React components
│   │   ├── App.tsx       # Main app with panels
│   │   └── main.tsx      # Entry point
│   ├── package.json
│   └── vite.config.ts
│
└── README.md
```

## 🐛 Troubleshooting

### Backend Issues

**Import errors:**
```bash
pip install -r requirements.txt --upgrade
```

**Port already in use:**
```bash
# Edit backend/.env
API_PORT=8001
```

### Frontend Issues

**Dependencies not installing:**
```bash
rm -rf node_modules package-lock.json
npm install
```

**Electron not starting:**
```bash
npm run dev:vite  # Run Vite only first
# Then in another terminal:
npm run dev:electron
```

## 🌟 Next Steps

1. Add your Anthropic API key to `backend/.env`
2. Start building your first social media post!
3. Explore the panel system by dragging and docking
4. Let AI assist with captions and scheduling

Need help? Check out the docs or reach out to the community!
