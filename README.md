# ⚡ PolyTerminal (Bloomberg Edition)

A professional-grade, real-time terminal dashboard for monitoring **Kalshi** and **Polymarket** prediction markets. Built for professional traders with a focus on cross-platform arbitrage.

## 🛡️ Security
PolyTerminal is designed with security as a priority:
- **Local Signing**: Your private keys never leave your machine. Polymarket orders are signed locally using the `py-clob-client` SDK.
- **Environment Isolation**: All sensitive credentials (API Keys, Secrets, Private Keys) are stored in `.env` and excluded from Git via `.gitignore`.
- **Zero-Storage**: The terminal does not store your keys in any database; they are loaded into memory only during runtime.

- **Multi-Platform Monitoring** — Side-by-side view of Kalshi (USD) and Polymarket (USDC) events.
- **Bloomberg-Style UI** — High-contrast, professional-grade TUI with sub-panels and state monitoring.
- **Arbitrage Engine** — Integrated fuzzy-matching and spread calculation between platforms.
- **Secure Integration** — Supports Kalshi RSA authentication and Polymarket REST APIs.
- **Mock Mode** — Automatic fallback to simulated data if no credentials are found.

## Quick Start

### 1. Create a Virtual Environment
Arch Linux (and most modern distros) requires a virtual environment to avoid conflicts with system packages.

```bash
python -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your Kalshi credentials. Polymarket public data works out of the box.

### 3. Run the Terminal

```bash
python terminal_app.py
```

## Controls

| Key | Action |
|-----|--------|
| `↑` `↓` | Navigate market lists |
| `R` | Refresh all data sources |
| `A` | Toggle Arbitrage Scanner details |
| `Q` | Quit terminal |

## Project Structure

- `terminal_app.py`: Main Bloomberg-style TUI.
- `kalshi_client.py`: Kalshi API interface (RSA/Demo/Prod).
- `polymarket_client.py`: Modern Polymarket Gamma & CLOB interface.
- `arb_engine.py`: Logic for market matching and arbitrage logic.

## License

MIT

---

Made with ❤️ by Kapil