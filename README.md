# Añil Randomlocke AI Agent (Discord-controlled)

This project runs a local AI agent that can play **Pokémon Añil: Definitive Edition** Randomlocke on Windows by:

- Reading game state/events from an in-game Ruby TCP bridge (`agent_bridge.rb`).
- Capturing the game window screenshot.
- Asking **Gemini (`gemini-3-pro-preview`)** for the next action as strict JSON.
- Sending keypresses to the game window.
- Posting controls + reports to Discord.

## Setup

### 1) Install the game bridge (one-time)

1. Copy `game_mod/agent_bridge.rb` into the game folder (same folder as `Game.exe`).
2. Patch `preload.rb` in the game folder to `require_relative "agent_bridge"`.
   - Copy/paste instructions are in `game_mod/preload.rb.patch.txt`.

### 2) Python environment

Requirements: **Python 3.11+** on Windows.

```powershell
cd anil-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

### 3) Configure

1. Create a `.env` from `.env.example` and fill keys.
2. Create `config.yaml` from `config.example.yaml` and fill Discord channel IDs + window title substring.
   - `agent.summary_mode: gemini` enables LLM-generated funny summaries (structured JSON).

### 4) Run

```powershell
python -m anil_agent.main --config config.yaml
```

Discord slash commands: `/start /pause /resume /stop /status /screenshot` (and optional `/thinking`).

### Optional local smoke tests

```powershell
# Bridge: 100x ping/state/events (game must be running + patched)
python -m anil_agent.main --config config.yaml --bridge-test

# Window capture: saves one PNG into logs/<run_id>/
python -m anil_agent.main --config config.yaml --screenshot-test
```

## Outputs

- Runtime logs: `logs/<run_id>/...`
- Daily reports: `reports/YYYY-MM-DD/report.json` + screenshots under `captures/` and `deaths/`.
