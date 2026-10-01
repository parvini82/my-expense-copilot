# 💰 Event-Driven Personal Expense Tracking AI Agent

An event-driven, production-ready asynchronous Python backend combining **FastAPI**, **Telegram Bot (python-telegram-bot v20+)**, **LangChain (OpenRouter)**, **Pandas Financial Data Analytics**, **OpenAI Whisper**, **Google Sheets API**, and **Docker** to automatically categorize personal expenses and incomes triggered by mobile bank notifications.

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
    [Telegram Bot Alert (Multi-User)] ──► "Transaction of $42.50 detected. What was this for?"
          │
          ▼
    [User Reply: Text or Voice Note]
          │
          ├── (If Voice Note: Transcribe via OpenAI Whisper API)
          │
          ▼
    [LangChain + OpenRouter] ──► Structured Output (ExpenseRecord)
          │
          ├── Hierarchical Taxonomy (Category + Sub-Category)
          ├── Shared Expense Refunds / Dong Detection (is_refund=True)
          ├── Generates clean description
          │
          ▼
    [Database Persistence] ──► Saves to Google Sheets (Fallback: expenses.json)
          │
          ▼
    [Telegram Confirmation] ──► Sends formatted receipt with Sub-Category & Refund Badge
```

---

## ✨ Features

- 📱 **Mobile Webhook Integration**: Listens for automated bank notifications from iOS Shortcuts, Tasker, or MacroDroid.
- 👥 **Multi-User Telegram Support**: Configurable list of authorized Telegram Chat IDs (`ALLOWED_CHAT_IDS`).
- 🏷️ **Hierarchical Categorization**: Automatically maps transactions to Main Category and Sub-category.
- 🔄 **Shared Expense Refund ("Dong") Rule**: Identifies repayments (e.g., "دنگ", "سهم") and flags them as `is_refund=True`.
- 🎙️ **Voice Note Processing**: Supports Persian and English audio notes transcribed via OpenAI Whisper.
- 📊 **Natural Language Financial QA (`/ask`)**: Query expenses using an integrated Pandas DataFrame AI agent.
- 📈 **Visual Monthly Expense Reports (`/report`)**: Generates high-resolution pie charts with Persian typography support.
- 🎯 **Budget Tracking & Alerts (`/budget`)**: Monitors category limits and sends automatic over-budget notifications.
- ☁️ **Google Sheets Integration**: Real-time sync with Google Sheets (gspread) with thread-safe JSON file fallback.
- 🐳 **Docker Production Ready**: Pre-configured `Dockerfile` and `docker-compose.yml` with persistent volume mounts.

---

## 📊 Category & Sub-Category Taxonomy

The AI categorizes all transactions into a structured two-level hierarchy:

### Expenses
- **Food & Dining**: Personal Meals / Social & Cafe / Snacks & Daily Treats / Supermarket
- **Relationship & Partner**: Date & Outings / Gifts & Shopping
- **Transportation**: Ride-hailing / Fuel & Car / Public Transit
- **Personal Care & Shopping**: Clothing / Grooming & Hygiene
- **Bills & Utilities**: Mobile Data / Subscriptions
- **Healthcare**: Pharmacy / Doctor Visits
- **Savings & Investments**: Vault Transfer / Gold & Crypto

### Incomes & Refunds
- **Salary & Earnings**: Fixed Salary / Bonus & Project
- **Family**: Allowance from Father / Gifts
- **Internal Transfers**: Savings Transfer
- **Shared Expense Refunds ("Dong")**: Friends' Share / Shared Purchase (`is_refund=True`)
- **Other**: Bank Interest / Miscellaneous

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
│   │   ├── llm_parser.py    # LangChain OpenRouter LLM structured parser
│   │   ├── qa_agent.py      # Pandas DataFrame natural language QA agent (/ask)
│   │   ├── reporting.py     # Matplotlib pie chart generator (/report)
│   │   ├── budget.py        # Category budget alert module (/budget)
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
│   ├── test_google_sheets.py # Google Sheets mock unit tests
│   └── test_advanced_features.py # Budget alerts, QA agent, & chart tests
├── Dockerfile               # Production Docker container image build
├── docker-compose.yml       # Docker Compose setup with volume persistence
├── requirements.txt         # Project dependencies
├── google_credentials.json  # Google Cloud Service Account credentials (Optional)
├── .env.example             # Environment template
└── README.md                # Documentation & setup guide
```

---

## ⚙️ Prerequisites & Setup

### Option A: Local Setup

1. **Clone & Install Dependencies**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure Environment Variables**:
   ```bash
   cp .env.example .env
   ```

   Edit `.env` with your actual credentials:
   ```env
   # Telegram Bot (Get token from @BotFather)
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
   
   # Authorized Telegram Chat IDs (Comma-separated list for multi-user support)
   ALLOWED_CHAT_IDS=123456789,987654321

   # OpenRouter LLM Configuration
   OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
   OPENROUTER_MODEL=google/gemini-2.5-flash-exp:free

   # OpenAI (for Whisper Voice Notes)
   OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

   # Webhook Security
   WEBHOOK_SECRET=my_super_secret_webhook_key_12345

   # Google Sheets Integration (Optional)
   GOOGLE_SHEET_ID=your_google_sheet_id_here
   GOOGLE_CREDENTIALS_FILE=google_credentials.json

   # Server & DB
   DB_FILE_PATH=expenses.json
   DEFAULT_CURRENCY=Toman
   HOST=0.0.0.0
   PORT=8000
   DEBUG=false
   ```

3. **Run the Application**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

---

### Option B: Docker Setup 🐳

1. **Configure `.env`** as shown above.
2. **Build and Run with Docker Compose**:
   ```bash
   docker-compose up -d --build
   ```
3. **View Container Logs**:
   ```bash
   docker-compose logs -f
   ```

---

## 🛠 Telegram Bot Commands

| Command | Description |
| :--- | :--- |
| `/ask [question]` | Ask natural language questions (e.g. `/ask چقدر این ماه خرج کافه کردم؟`) |
| `/report [YYYY-MM]` | Generate visual pie chart report and monthly budget summary |
| `/budget` | View monthly category spending limits and budget status |
| `/expenses` | View recently logged expenses |
| `/pending` | Inspect active pending transaction waiting for explanation |
| `/cancel` | Cancel active pending transaction |
| `/help` | Display interactive command guide |

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

**Expected Webhook Response:**
```json
{
  "status": "success",
  "message": "Bank notification processed and Telegram alert dispatched.",
  "detected_amount": 42.5,
  "app_name": "Chase Mobile"
}
```

The Telegram bot will send an alert to all authorized `ALLOWED_CHAT_IDS`:
> 🔔 **New Transaction Detected!**
> 💰 **Amount:** `$42.50`
> 📱 **Source:** `Chase Mobile`
> 📝 **Details:** `Chase: You made a purchase of $42.50 at WHOLE FOODS with card ending 1234.`
> 
> 👉 **What was this for?** *(Reply with a text message or voice note)*

---

## 📱 Mobile Automation Setup

### iOS Shortcuts Setup
1. Open **Shortcuts** app -> **Automation** -> **Personal Automation**.
2. Trigger: **Transaction** (Apple Pay) or **App** notification.
3. Action: **Get Contents of URL**:
   - URL: `https://your-domain.com/webhook/mobile`
   - Method: `POST`
   - Headers: `x-secret-key` : `my_super_secret_webhook_key_12345`
   - Request Body: `JSON`
     - `text`: `Shortcut Input` or Notification Content
     - `app_name`: `Apple Pay` / `Bank App`

### Android (Tasker / MacroDroid) Setup
1. Trigger: **Notification Intercept** matching bank app.
2. Action: **HTTP Request** -> `POST` to `/webhook/mobile`.
3. Header: `x-secret-key: my_super_secret_webhook_key_12345`.
4. Body: `{"text": "%NTITLE %NTEXT", "app_name": "%NAPP"}`.

---

## 🧪 Running Tests

Run the full test suite using Python `unittest` or `pytest`:

```bash
python3 -m unittest discover -s tests
```
