# 🖥️ Dashboard Kaseya VSA 9.5

Monitoring dashboard for Kaseya VSA 9.5 — FastAPI backend + HTML/JS frontend.

## Features

- 📊 Real-time agent monitoring (online/offline status)
- 🔍 Agent details: name, group, OS, IP address
- 🎨 Dark theme dashboard
- 🔄 Auto-refresh every 5 minutes

## Prerequisites

- Python 3.11+
- Access to Kaseya VSA 9.5 instance

## Setup

1. **Clone the repo**
   ```bash
   git clone git@github.com:irsanrochendi/DashboardKaseyaAST.git
   cd DashboardKaseyaAST
   ```

2. **Install dependencies**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your Kaseya credentials
   ```

4. **Get session token from browser**
   - Login to Kaseya VSA web UI
   - Open F12 → Console → type `document.cookie`
   - Copy the `sessionToken=` value
   - Paste it in `.env` as `KASEYA_SESSION_TOKEN`

5. **Run the backend**
   ```bash
   python -c "import uvicorn; from main import app; uvicorn.run(app, host='127.0.0.1', port=3000)"
   ```

6. **Open dashboard**
   - Browser: `http://127.0.0.1:3000`

## Project Structure

```
DashboardKaseyaAST/
├── backend/
│   ├── main.py           # FastAPI server
│   ├── kaseya_client.py  # Kaseya API client
│   ├── config.py         # Configuration loader
│   └── requirements.txt  # Python dependencies
├── frontend/
│   ├── index.html        # Dashboard HTML
│   ├── style.css         # Dark theme styles
│   └── app.js            # Frontend logic
├── .env.example          # Environment template
├── .gitignore
└── README.md
```

## Notes

- Session token expires — refresh from browser when needed
- Kaseya VSA 9.5 with 2FA requires session token (Personal Token Auth is blocked)
- Only `/api/v1.0/assetmgmt/agents` endpoint is available in this Kaseya version

## Author

**Irsan** — IT Support & Networking
