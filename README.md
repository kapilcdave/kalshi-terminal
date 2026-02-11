# ⚡ Kalshi Live Terminal

A sleek, real-time terminal dashboard for monitoring [Kalshi](https://kalshi.com) prediction markets. Built with [Textual](https://textual.textualize.io/) for a rich TUI experience.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **Live Market Data** — Streams active Kalshi markets with bid/ask prices and volume
- **Market Detail View** — Select any market to see price sparklines and stats
- **Keyboard Navigation** — Arrow keys to browse, `R` to refresh, `Q` to quit
- **Mock Mode** — Runs with simulated data if no API credentials are provided
- **Secure Auth** — RSA key-based authentication (no passwords stored)

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/YOUR_USERNAME/kalshi-terminal.git
cd kalshi-terminal
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure API Keys

Generate an API key from your [Kalshi Dashboard](https://kalshi.com/account/details).

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
KALSHI_API_KEY=your_api_key_id
KALSHI_PRIVATE_KEY_FILE=./your_private_key.pem
KALSHI_ENV=demo
```

### 3. Run

```bash
python terminal_app.py
```

> **No API key?** The app will start in **mock mode** with simulated market data so you can preview the UI.

## Controls

| Key | Action |
|-----|--------|
| `↑` `↓` | Navigate markets |
| `Enter` | Select market (updates detail view) |
| `R` | Refresh market list |
| `Q` | Quit |

## Project Structure

```
├── terminal_app.py      # Main TUI application (Textual)
├── kalshi_client.py     # Kalshi API wrapper with RSA auth
├── requirements.txt     # Python dependencies
├── .env.example         # Template for environment variables
└── .gitignore           # Git ignore rules
```

## Tech Stack

- **[Textual](https://textual.textualize.io/)** — Modern Python TUI framework
- **[kalshi-python-async](https://pypi.org/project/kalshi-python-async/)** — Official async Kalshi SDK
- **[python-dotenv](https://pypi.org/project/python-dotenv/)** — Environment variable management

## License

MIT

---

Made with ❤️ by Kapil