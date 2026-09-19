# 📅 CalAI — Production-Ready AI Calendar Agent

> Chat with your Google Calendar using natural language. Built with FastAPI, LangChain, Gemini, and MongoDB.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green)
![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## ✨ Features

- 🤖 **AI-powered** — Natural language scheduling via Google Gemini
- 📅 **Full Calendar CRUD** — Create, read, update, delete events
- 🕐 **Smart scheduling** — Conflict detection & free slot finder
- 👥 **Multi-user** — Each user connects their own Google Calendar via OAuth
- 🔐 **Secure** — Encrypted OAuth token storage in MongoDB
- 📊 **Observable** — LangSmith tracing, structured JSON logging
- 🚀 **Deployable** — Docker + Railway/Render ready
- 💬 **Beautiful Chat UI** — Dark mode, glassmorphism, animated

---

## 🛠️ Setup Guide

### Step 1 — Clone & Install

```bash
git clone <your-repo>
cd calender_agent

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Mac/Linux

pip install -e .
```

### Step 2 — Google Cloud Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (e.g., `calender-agent`)
3. **Enable APIs:**
   - `APIs & Services` → `Library` → Search **"Google Calendar API"** → **Enable**
   - Search **"Google People API"** → **Enable** (for user profile)
4. **Create OAuth Credentials:**
   - `APIs & Services` → `Credentials` → `+ Create Credentials` → `OAuth 2.0 Client ID`
   - Application type: **Web application**
   - Authorized redirect URIs: `http://localhost:8000/auth/callback`
   - Download the JSON — **copy** `client_id` and `client_secret`
5. **OAuth Consent Screen:**
   - `APIs & Services` → `OAuth consent screen`
   - User Type: **External** → Fill in app name → Add scopes: `calendar`, `email`, `profile`
   - Add your email as a **Test user**

### Step 3 — MongoDB Atlas

1. Go to [cloud.mongodb.com](https://cloud.mongodb.com)
2. Create a free **M0** cluster
3. `Database Access` → Add user (remember password)
4. `Network Access` → Add IP `0.0.0.0/0` (dev) or your server IP (prod)
5. `Clusters` → `Connect` → `Drivers` → Copy connection string

### Step 4 — Get API Keys

| Key | Where |
|---|---|
| **Gemini API Key** | [aistudio.google.com](https://aistudio.google.com) → Get API Key |
| **LangSmith Key** | [smith.langchain.com](https://smith.langchain.com) → Settings → API Keys |

### Step 5 — Configure .env

```bash
cp .env.example .env
```

Fill in `.env`:
```env
APP_SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_hex(32))">
GOOGLE_API_KEY=<your gemini key>
GOOGLE_CLIENT_ID=<from GCP credentials>
GOOGLE_CLIENT_SECRET=<from GCP credentials>
MONGODB_URL=<your atlas connection string>
LANGCHAIN_API_KEY=<your langsmith key>
ENCRYPTION_KEY=<generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
```

### Step 6 — Run Locally

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open: **http://localhost:8000**

---

## 🐳 Docker

```bash
# Start with local MongoDB
docker-compose up --build

# Stop
docker-compose down
```

---

## 🚀 Deploy to Railway

1. Push to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Add MongoDB service (or use MongoDB Atlas)
4. Set all environment variables in Railway dashboard
5. Update `GOOGLE_REDIRECT_URI` to your Railway URL: `https://your-app.railway.app/auth/callback`
6. Add this URI to GCP OAuth authorized redirect URIs

## 🚀 Deploy to Render

1. Push to GitHub
2. Go to [render.com](https://render.com) → New → Web Service
3. Connect your repo → Select Dockerfile
4. Add all environment variables
5. Update `GOOGLE_REDIRECT_URI` to: `https://your-app.onrender.com/auth/callback`

---

## 📡 API Reference

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/health` | GET | No | Liveness check |
| `/ready` | GET | No | Readiness check |
| `/auth/login` | GET | No | Start Google OAuth |
| `/auth/callback` | GET | No | OAuth callback |
| `/auth/me` | GET | JWT | Current user info |
| `/auth/logout` | POST | JWT | Logout |
| `/agent/chat` | POST | JWT | Chat with agent |
| `/agent/sessions` | GET | JWT | List sessions |
| `/agent/sessions/{id}` | GET | JWT | Session messages |
| `/agent/sessions/{id}` | DELETE | JWT | Delete session |
| `/docs` | GET | No | Swagger UI (dev only) |

---

## 🧪 Testing

```bash
pytest tests/ -v --cov=app --cov-report=term-missing
```

---

## 🏗️ Architecture

```
Request → FastAPI → JWT Auth → Rate Limiter
                             ↓
                    Agent Route → Google Calendar Service (OAuth tokens from MongoDB)
                             ↓
                    LangChain Agent (Gemini LLM)
                             ↓
                    Calendar Tools → Google Calendar API
                             ↓
                    MongoDB (save messages) → Response
```

---

## 📁 Project Structure

```
calender_agent/
├── app/
│   ├── agent/          # LangChain agent + prompts + memory
│   ├── api/            # FastAPI routes + middleware
│   ├── core/           # Exceptions, logging, security
│   ├── db/             # MongoDB models (Beanie)
│   ├── services/       # Google Calendar + OAuth services
│   ├── static/         # Web Chat UI (HTML/CSS/JS)
│   ├── tools/          # LangChain tools
│   ├── config.py       # Pydantic Settings
│   └── main.py         # FastAPI app entry point
├── tests/
├── scripts/
├── Dockerfile
├── docker-compose.yml
├── railway.toml
└── render.yaml
```
