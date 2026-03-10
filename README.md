# Genie v2

AI-powered SMS assistant for small businesses. Genie handles customer inquiries, books appointments, tracks leads, and sends re-engagement messages - all via text.

## Features

- **Smart Customer Service** - AI answers questions about services, pricing, hours
- **Appointment Scheduling** - Book, reschedule, and cancel via text  
- **Lead Tracking** - Automatically captures and tracks potential customers
- **Re-engagement Campaigns** - Automated follow-ups to bring customers back
- **Owner Dashboard** - Simple web interface to monitor everything

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐
│  Telegram   │────▶│   Gateway   │────▶│  Master Agent   │
│  (or SMS)   │     │  (Express)  │     │  (Orchestrator) │
└─────────────┘     └─────────────┘     └────────┬────────┘
                                                 │
                    ┌────────────────────────────┼────────────────────────────┐
                    │                            │                            │
              ┌─────▼─────┐              ┌───────▼───────┐            ┌───────▼───────┐
              │ Customer  │              │  Scheduling   │            │    Leads &    │
              │  Service  │              │    Agent      │            │ Re-engagement │
              └───────────┘              └───────────────┘            └───────────────┘
```

## Quick Start

### Prerequisites

- Node.js 18+
- Python 3.10+
- SQLite3

### Setup

1. Clone the repo:
```bash
git clone https://github.com/devgreeny/geniev2.git
cd geniev2
```

2. Create `.env` file with your API keys:
```bash
ANTHROPIC_API_KEY=your_key
TELEGRAM_BOT_TOKEN=your_token  # or Vonage for SMS
AGENTFIELD_URL=http://localhost:8080
```

3. Install dependencies:
```bash
# Gateway
cd gateway && npm install

# Agents  
cd ../agents && pip install -r requirements.txt
```

4. Seed test data:
```bash
python scripts/seed-test.py
```

5. Run locally:
```bash
./run-local.sh
```

### Dashboard

```bash
cd dashboard && npm install && npm run dev
```

Open http://localhost:5173

## Project Structure

```
genie/
├── agents/                 # Python AI agents
│   ├── master/            # Routes messages to specialists
│   ├── customer_service/  # Handles customer inquiries
│   ├── scheduling/        # Appointment management
│   ├── leads/             # Lead tracking & re-engagement
│   └── shared/            # Database & utilities
├── gateway/               # Express.js SMS/Telegram gateway
├── dashboard/             # React admin dashboard
└── scripts/               # Utility scripts
```

## Tech Stack

- **Agents**: Python + AgentField + Claude AI
- **Gateway**: Node.js + Express + better-sqlite3
- **Dashboard**: React + Vite
- **Database**: SQLite

## License

MIT
