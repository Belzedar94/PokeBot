# Añil Randomlocke AI Agent (Discord-controlled)

This project lets an AI agent play **Pokémon Añil: Definitive Edition** on your Windows PC while you control it from Discord.

It works by:

- Reading game state/events from a small “bridge” file inside the game folder
- Taking screenshots of the game window
- Asking Gemini what buttons to press (as strict JSON)
- Pressing those keys for you
- Posting reports to Discord when you earn a badge (captures + deaths)

## Before you start (important)

- Keep your `.env` file private. It contains your Discord bot token and Gemini API key.
- The agent uses screenshots of the game window. Keep the game visible and not covered by other windows.
- The agent focuses the game window to press keys. If it steals focus while you type in Discord, pause the agent first or use Discord from your phone/another device.

## What you need

- Windows 10/11
- Python 3.11 or 3.12 installed
- Discord desktop app (for streaming)
- A Discord server where you can add a bot (or create one)
- A Gemini API key (Google)

## Step 1 — Prepare the game (install the bridge)

The agent needs the game to expose state/events through a local connection. That is what `agent_bridge.rb` does.

If you use the game copy inside this repo (`ROM/`), it’s already set up:

- `ROM/agent_bridge.rb` exists
- `ROM/preload.rb` ends with `require_relative "agent_bridge"`

If you are using a different copy of the game, do this once:

1. Find your game folder (the folder that contains `Game.exe`).
2. Copy `anil-agent/game_mod/agent_bridge.rb` into that game folder (next to `Game.exe`).
3. Edit the file `preload.rb` in that game folder:
   - Right-click `preload.rb` → “Open with” → Notepad
   - Scroll to the bottom
   - Add this on a new line:
     - `require_relative "agent_bridge"`
   - Save the file
4. Close and re-open the game.

If Windows shows a Firewall popup for the game, allow it (the bridge only listens on your own PC at `127.0.0.1`).

## Step 2 — Create a Discord bot and invite it to your server

The agent is controlled through Discord slash commands (like `/start`).

1. Open the Discord Developer Portal: https://discord.com/developers/applications
2. Click “New Application” and give it a name (example: “Anil Agent”).
3. In the left sidebar, click “Bot” → “Add Bot”.
4. On the “Bot” page, copy the token.
   - You will paste it into a file called `.env` later.
   - Do not share the token; anyone with it can control your bot.
5. Invite the bot to your server:
   - Go to “OAuth2” → “URL Generator”
   - Scopes:
     - `bot`
     - `applications.commands`
   - Bot Permissions (minimum recommended):
     - “Send Messages”
     - “Attach Files”
     - “Read Message History” (optional but helpful)
   - Copy the generated URL, open it in your browser, pick your server, click Authorize.

## Step 3 — Get your Discord channel IDs (numbers)

The config needs the channel IDs so the bot knows where to post reports.

1. In Discord (desktop app), open “User Settings” (gear icon).
2. Go to “Advanced”.
3. Turn on “Developer Mode”.
4. Now you can copy IDs:
   - Right-click a channel → “Copy ID”
   - (Optional) Right-click the server name → “Copy ID” (this is the “Guild ID”)

What each ID is used for:

- `control_channel_id`: where `/screenshot` gets posted (if set to `0`, screenshot replies privately to you)
- `captures_channel_id`: where it posts captures (at badge time)
- `deaths_channel_id`: where it posts deaths (at badge time)
- `announce_channel_id`: where it posts “badge earned → paused”
- `guild_id` (optional, recommended): makes slash commands appear immediately in your server

Tip: create channels like `#agent-control`, `#agent-captures`, `#agent-deaths`, then copy their IDs.

## Step 4 — Get a Gemini API key

You need a Gemini API key from Google. Create one in Google AI Studio / Gemini API settings, then you’ll paste it into `.env`.

## Step 5 — Install Python 3.11+ (one-time)

1. Install Python 3.11 or 3.12 from https://www.python.org/downloads/
2. During installation, make sure “Add python.exe to PATH” is checked.
3. Open PowerShell and confirm:

```powershell
python --version
```

It should say `Python 3.11.x` or `Python 3.12.x`.

## Step 6 — Install the project (copy/paste commands)

Open PowerShell, then run:

```powershell
cd anil-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

If you get an error about scripts being disabled when running `Activate.ps1`, run this once, then try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

## Step 7 — Configure `.env` (keys) and `config.yaml` (settings)

### 7A) Create `.env`

1. In the `anil-agent/` folder, copy `.env.example`
2. Rename the copy to `.env`
3. Open `.env` with Notepad
4. Fill in:
   - `GEMINI_API_KEY=...` (your Gemini key)
   - `DISCORD_BOT_TOKEN=...` (your Discord bot token)
5. Save

### 7B) Create `config.yaml`

1. In the `anil-agent/` folder, copy `config.example.yaml`
2. Rename the copy to `config.yaml`
3. Open `config.yaml` with Notepad
4. Fill these:

- `game.window_title_contains`
  - Start the game (`ROM/Game.exe`) and look at the title at the top of the window.
  - Put a short piece of that title here. Example: `Pokemon Anil`

- `discord.control_channel_id`, `discord.captures_channel_id`, `discord.deaths_channel_id`, `discord.announce_channel_id`
  - Paste the numbers you got from “Copy ID”

- `discord.guild_id` (optional, recommended)
  - Paste your server ID (right-click server name → “Copy ID”)

- `agent.summary_mode`
  - `template` = free, instant summaries
  - `gemini` = Gemini generates 1 funny line in Spanish per capture/death (costs API calls)

## Step 8 — Run the bot + agent

1. Start the game first:
   - Run `ROM/Game.exe`
   - Leave the game visible on screen (don’t cover it with other windows)
2. In PowerShell (in `anil-agent/` with the venv activated), run:

```powershell
python -m anil_agent.main --config config.yaml
```

3. In Discord, try:
   - `/status` (shows agent status)
   - `/screenshot` (posts a screenshot to the control channel, if configured)
   - `/start` (starts playing)
   - `/pause` and `/resume`
   - `/stop`

Badge behavior:

- When the game reports a badge was earned, the agent pauses automatically.
- It posts all unreported captures and deaths (with screenshots) to your configured channels.
- Resume with `/resume`.

## Streaming the agent’s gameplay from your personal Discord account

You stream from your own Discord account while the agent plays locally on your PC.

### Option A (recommended): Discord “Go Live” (window stream)

1. Open Discord (desktop app).
2. Join a voice channel in your server (or start a call).
3. Click “Share Your Screen”.
4. Select the game window (the one showing `Game.exe` / “Pokemon Anil”).
5. Choose a stream quality and click “Go Live”.

Tips:

- Stream the game window (not your whole monitor) so you don’t accidentally show your `.env` file or other private info.
- Keep the game window unobstructed, or the agent will “see” other windows instead of the game.
- If the agent keeps stealing focus while you type in Discord, pause it first or use Discord on your phone/another device.

If the stream shows a black screen:

- Try switching the game between windowed/fullscreen.
- In Discord settings → “Voice & Video”, toggle the screen capture options (Discord sometimes has a “latest capture technology” toggle).
- Try disabling Discord hardware acceleration (Discord settings → “Advanced”).

## Optional smoke tests (quick checks)

```powershell
# Bridge: 100x ping/state/events (game must be running + patched)
python -m anil_agent.main --config config.yaml --bridge-test

# Window capture: saves one PNG into logs/<run_id>/
python -m anil_agent.main --config config.yaml --screenshot-test
```

## Outputs

- Runtime logs: `logs/<run_id>/...`
- Daily reports: `reports/YYYY-MM-DD/report.json` and screenshots under `captures/` and `deaths/`

