# Scian Flow - Production Tracking System

A complete production tracking and review system for VFX, animation, and media production. Built from scratch inspired by **ShotGrid**, **Frame.io**, and **CineSync**.

## 🎬 What Is This?

Scian Flow is a **desktop-first production tracking application** designed for studios with network storage. It tracks shots, versions, and reviews WITHOUT requiring file uploads - everything stays on your network storage.

### Key Features

✅ **Project Management** - Organize productions into projects, sequences, and shots
✅ **Shot Tracking** - Track status, priority, and progress through the pipeline
✅ **Version Registration** - Link to files on network storage (no uploads!)
✅ **Video Review** - Built-in video player with timeline controls
✅ **Frame-Accurate Comments** - Add notes at specific frames
✅ **Team Collaboration** - Multiple users, activity tracking
✅ **Desktop App** - Built with Electron for fast, local performance

## 🏗️ Architecture

### Backend (FastAPI + SQLite/PostgreSQL)
- **Database Models**: Projects, Sequences, Shots, Assets, Tasks, Versions, Comments, Users, Activity
- **RESTful API**: Complete CRUD operations for all entities
- **File Path Storage**: Stores paths, not files (no upload bottleneck!)
- **SQLAlchemy ORM**: Proper relationships and cascade deletes

### Frontend (React + TypeScript + Tailwind)
- **Modern UI**: Clean, dark theme optimized for long hours
- **Type-Safe**: Full TypeScript with matching backend types
- **Component-Based**: Dashboard → Project → Shot → Review workflow
- **Axios Client**: Type-safe API calls

### How It Works

```
Artist Workflow:
1. Render shot → /mnt/projects/show/shots/SH010/v003.mp4
2. Open Scian desktop app
3. Navigate to shot → Click "Add Version"
4. Paste file path → Done! (No upload, instant)

Supervisor Workflow:
1. Open Scian desktop app
2. Navigate to shot → Select version
3. Video plays directly from network path
4. Click timeline → Add comment with annotation
5. Mark as "Approved" or "Changes Needed"

Everyone sees same data - stored in shared database!
```

## 📊 Data Model

```
Project
├── Sequences
│   └── Shots
│       ├── Versions (file paths)
│       │   └── Comments (frame-accurate)
│       └── Tasks
└── Assets
    ├── Versions
    └── Tasks

Users
Activity Feed
```

## 🚀 Getting Started

### Prerequisites
- Python 3.11+
- Node.js 18+
- Network storage accessible to all workstations

### Backend Setup

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Start server
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# API docs available at: http://localhost:8000/docs
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev

# Or build Electron app
npm run build:electron
```

## 📍 API Endpoints

### Projects
- `GET /api/projects/` - List all projects
- `POST /api/projects/` - Create project
- `GET /api/projects/{id}` - Get project details
- `PUT /api/projects/{id}` - Update project
- `DELETE /api/projects/{id}` - Delete project

### Shots
- `GET /api/shots/?project_id={id}` - List shots by project
- `POST /api/shots/` - Create shot
- `GET /api/shots/{id}` - Get shot details
- `PUT /api/shots/{id}` - Update shot
- `DELETE /api/shots/{id}` - Delete shot

### Versions
- `GET /api/versions/?shot_id={id}` - List versions by shot
- `POST /api/versions/` - Register new version (file path)
- `POST /api/versions/validate-path` - Validate file path exists

### Comments
- `GET /api/comments/?version_id={id}` - List comments
- `POST /api/comments/` - Add comment with optional annotation
- `GET /api/comments/{id}/replies` - Get comment thread

### Users & Activity
- `GET /api/users/` - List users
- `POST /api/users/` - Create user
- `GET /api/activity/` - Get activity feed

## 🎨 Status System

### Shot/Task Status
- **WTG** (Waiting) - Not started yet
- **RDY** (Ready) - Ready to begin
- **IP** (In Progress) - Currently being worked on
- **REV** (Review) - Ready for supervisor review
- **APP** (Approved) - Approved, no changes needed
- **HLD** (On Hold) - Changes requested
- **FIN** (Final) - Locked and final
- **OMT** (Omitted) - Not needed anymore

### Priority Levels
- **Low** - Can wait
- **Medium** - Normal priority
- **High** - Important
- **Critical** - Urgent, blocking

## 🎯 Example Workflow

### 1. Create a Project
```bash
curl -X POST http://localhost:8000/api/projects/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Summer Campaign 2025",
    "code": "SUM25",
    "description": "Q2 marketing campaign",
    "status": "ip"
  }'
```

### 2. Create a User
```bash
curl -X POST http://localhost:8000/api/users/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "artist@studio.com",
    "name": "John Artist",
    "password": "temp123",
    "department": "animation",
    "role": "Artist"
  }'
```

### 3. Add a Shot
```bash
curl -X POST http://localhost:8000/api/shots/ \
  -H "Content-Type: application/json" \
  -d '{
    "sequence_id": 1,
    "name": "Hero Shot 010",
    "code": "SH010",
    "frame_start": 1,
    "frame_end": 120,
    "fps": 24,
    "status": "ip",
    "priority": "high"
  }'
```

### 4. Register a Version
```bash
curl -X POST http://localhost:8000/api/versions/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "SH010_v003",
    "version_number": 3,
    "file_path": "/mnt/projects/sum25/shots/SH010/renders/SH010_v003.mp4",
    "file_name": "SH010_v003.mp4",
    "shot_id": 1,
    "uploaded_by_id": 1,
    "fps": 24
  }'
```

### 5. Add a Comment
```bash
curl -X POST http://localhost:8000/api/comments/ \
  -H "Content-Type: application/json" \
  -d '{
    "version_id": 1,
    "author_id": 1,
    "text": "Logo needs to be 20% bigger",
    "comment_type": "revision",
    "frame_number": 247,
    "annotation_data": {
      "shapes": [
        {
          "type": "circle",
          "x": 500,
          "y": 300,
          "radius": 50,
          "color": "#FF0000"
        }
      ]
    }
  }'
```

## 🎨 Frontend Features

### Dashboard
- Grid of all projects
- Status indicators
- Quick project creation

### Project View
- Grid of all shots in project
- Status and priority badges
- Frame range info
- Quick shot creation

### Shot Detail View
- **Left Side**: Video player with timeline
- **Right Side**: Version list
- **Bottom**: Comments panel
- Add versions by file path
- Frame-accurate commenting

### Video Player
- Play/pause controls
- Timeline scrubber
- Frame counter
- Current time display
- Add comment at current frame

## 🔒 No File Uploads!

**Key Architectural Decision**: This app does NOT upload files to a server.

**Why?**
- ✅ **Fast** - No waiting for 50GB uploads
- ✅ **No duplication** - Files stay in one place
- ✅ **Scalable** - Database stores paths (tiny), not files (huge)
- ✅ **Network-friendly** - Only JSON goes over network

**How?**
- Artist renders to `/mnt/projects/show/shots/SH010/v003.mp4`
- App stores path in database
- Desktop app plays directly from network path
- Optional: Generate web-optimized proxies for remote users

## 🎯 Future Enhancements

### v1.1 - Drawing Annotations
- [ ] CineSync-style drawing canvas
- [ ] Freehand pen tool
- [ ] Arrows, circles, boxes
- [ ] Color picker
- [ ] Save drawings with comments

### v1.2 - Advanced Features
- [ ] Task board / Kanban view
- [ ] Asset tracking (not just shots)
- [ ] Version comparison (side-by-side)
- [ ] Export review PDFs
- [ ] Email notifications

### v2.0 - Collaboration
- [ ] Real-time presence (who's viewing what)
- [ ] WebSocket updates
- [ ] Web viewer for clients
- [ ] Mobile app for approvals

## 📦 Production Deployment

### Server Setup
```bash
# Install PostgreSQL
sudo apt install postgresql

# Create database
sudo -u postgres createdb scian_flow

# Update config
# backend/.env
DATABASE_URL=postgresql://user:pass@localhost/scian_flow
```

### Electron Build
```bash
cd frontend
npm run build:electron

# Output in dist-electron/
# Install on all workstations
```

### Network Configuration
Each workstation needs:
- Access to central database server
- Access to network storage (NFS/SMB mount)
- Scian desktop app installed

## 🤝 Inspired By

- **ShotGrid** (Autodesk) - Pipeline tracking, task management
- **Frame.io** (Adobe) - Frame-accurate comments, version control
- **CineSync** - Real-time review, annotation tools

## 📝 License

Built for studio production workflows. Customize as needed for your pipeline!

---

**Built with ❤️ for production teams who need simple, fast, effective tracking.**
