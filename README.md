# Superintendent AI — Construction Project Management

AI-powered project management for housing contractors. A superintendent provides a plain-text project description, and the AI handles task breakdown, contractor assignment, email outreach, reply monitoring, and schedule alerts.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your ANTHROPIC_API_KEY
python main.py
```

Open http://localhost:8000

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `RESEND_API_KEY` | No | Resend API key for real email sending |
| `RESEND_FROM_EMAIL` | No | Sender email for outreach |
| `GMAIL_USER` | No | Gmail address for IMAP polling |
| `GMAIL_APP_PASSWORD` | No | Gmail App Password for IMAP |
| `DATABASE_URL` | No | Defaults to `sqlite:///./superintendent.db` |
| `APP_PORT` | No | Defaults to `8000` |

## Usage

1. **Seed contractors**: happens automatically on first run (10 demo contractors)
2. **Create project**: Go to `/projects/new`, describe the build
3. **Generate plan**: AI breaks description into tasks
4. **Assign contractors**: AI matches tasks to contractors by specialty
5. **Run outreach**: AI drafts and sends professional emails
6. **Monitor**: AI checks project health, flags delays
