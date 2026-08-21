# 💰 Event-Driven Personal Expense Tracking AI Agent

An event-driven, production-ready asynchronous Python backend combining **FastAPI**, **Telegram Bot (python-telegram-bot v20+)**, **LangChain (OpenRouter / gpt-4o-mini)**, **OpenAI Whisper**, and local storage to automatically categorize personal expenses triggered by mobile bank notifications.

---

## 🏗️ Architecture & Workflow

```
[Mobile Bank Notification]
          │
          ▼
   (iOS Shortcut / Tasker)
          │  POST /webhook/mobile (JSON + x-secret-key)
          ▼
    [FastAPI Server] ──► Extracts Amount ──► Sets In-Memory State
          │
          ▼
    [Telegram Bot Alert] ──► "Transaction of $42.50 detected. What was this for?"
          │
          ▼
    [User Reply: Text or Voice Note]
          │
          ├── (If Voice: Transcribe via OpenAI Whisper API)
          │
          ▼
    [LangChain + OpenRouter gpt-4o-mini] ──► Structured Output (ExpenseRecord)
          │
          ├── Categorizes (Food & Dining, Groceries, Utilities, etc.)
          ├── Generates clean description
          │
          ▼
    [Mock JSON Database (expenses.json)] ──► Saves Record
          │
          ▼
    [Telegram Confirmation] ──► Sends formatted receipt back to user
```

---

## 📁 Project Structure

```
expense-agent/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, webhook routing, & shared lifespan
│   ├── config.py            # Pydantic BaseSettings & env validation
│   ├── state.py             # Thread-safe in-memory state manager for pending alerts
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── llm_parser.py    # LangChain ChatOpenAI configured for OpenRouter
│   │   └── audio.py         # Whisper voice transcription module
│   ├── bot/
│   │   ├── __init__.py
│   │   └── telegram_bot.py  # Telegram bot handlers & alert dispatcher
│   └── database/
│       ├── __init__.py
│       ├── google_sheets.py # Asynchronous Google Sheets persistence (gspread)
│       └── mock_db.py       # Local JSON persistence fallback (expenses.json)
├── tests/
│   ├── __init__.py
│   ├── test_agent.py        # Regex amount extraction, schema, state tests
│   ├── test_api.py          # FastAPI webhook & auth tests
│   └── test_google_sheets.py # Google Sheets mock unit tests
├── requirements.txt         # Project dependencies
├── google_credentials.json  # Google Cloud Service Account credentials
├── .env.example             # Environment template
└── README.md                # Documentation & setup guide
```

---

## ⚙️ Prerequisites & Setup

### 1. Clone & Install Dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit `.env` with your actual credentials:
```env
# Telegram Bot
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
ALLOWED_CHAT_ID=123456789

# OpenRouter (for LangChain GPT-4o-mini)
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=openai/gpt-4o-mini

# OpenAI (for Whisper Voice Notes)
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Webhook Security
WEBHOOK_SECRET=my_super_secret_webhook_key_12345

# Server & DB
DB_FILE_PATH=expenses.json
HOST=0.0.0.0
PORT=8000
DEBUG=false
```

> **Finding your Telegram Chat ID:**
> 1. Start your bot or message `@userinfobot` on Telegram.
> 2. Copy your user ID and set it as `ALLOWED_CHAT_ID`.

---

## 🚀 Running the Application

Start the combined FastAPI server and Telegram Bot:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 🧪 Testing the Webhook

Simulate a bank notification webhook with `curl`:

```bash
curl -X POST http://localhost:8000/webhook/mobile \
  -H "Content-Type: application/json" \
  -H "x-secret-key: my_super_secret_webhook_key_12345" \
  -d '{
    "text": "Chase: You made a purchase of $42.50 at WHOLE FOODS with card ending 1234.",
    "app_name": "Chase Mobile"
  }'
```

**Expected Response:**
```json
{
  "status": "success",
  "message": "Bank notification processed and Telegram alert dispatched.",
  "detected_amount": 42.5,
  "app_name": "Chase Mobile"
}
```

The Telegram bot will immediately send you a message:
> 🔔 **New Transaction Detected!**
> 💰 **Amount:** `$42.50`
> 📱 **Source:** `Chase Mobile`
> 📝 **Details:** `Chase: You made a purchase of $42.50 at WHOLE FOODS with card ending 1234.`
> 
> 👉 **What was this for?** *(Reply with a text message or voice note)*

---

## 📱 Setting up Mobile Automation

### iOS Shortcuts Setup
1. Open the **Shortcuts** app on iOS.
2. Go to the **Automation** tab -> Create **Personal Automation**.
3. Choose **Transaction** (Apple Pay) or **App** (e.g., when your bank app sends a notification).
4. Add action: **Get Contents of URL**:
   - URL: `https://your-domain.com/webhook/mobile`
   - Method: `POST`
   - Headers: `x-secret-key` : `my_super_secret_webhook_key_12345`
   - Request Body: `JSON`
     - `text`: `Shortcut Input` or Notification Content
     - `app_name`: `Apple Pay` / `Bank App`

### Android (Tasker / MacroDroid) Setup
1. Create a trigger on **Notification Intercept** matching your bank app.
2. Add action: **HTTP Request** -> `POST` to `/webhook/mobile`.
3. Set Header: `x-secret-key: my_super_secret_webhook_key_12345`.
4. Set Body: `{"text": "%NTITLE %NTEXT", "app_name": "%NAPP"}`.

---

## 🧪 Running Tests

Run the test suite using `pytest`:
```bash
pytest tests -v
```
