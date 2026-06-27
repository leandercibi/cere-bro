# Environment Variables for Hermes Configuration

The following environment variables must be set in Hermes config (e.g., `~/.hermes/env` or via Hermes gateway configuration):

## Required Variables

- **`DB_PATH`** — Path to SQLite database file
  - Default: `./data/cerebro.sqlite`
  - Example: `/home/user/personal-projects/cere-bro/data/cerebro.sqlite`

- **`VAULT_ROOT`** — Path to Obsidian vault root directory
  - Default: `./vault`
  - Example: `/home/user/personal-projects/cere-bro/vault`

- **`OPENROUTER_API_KEY`** — OpenRouter API key for LLM calls (calorie estimation, idea synthesis)
  - Required for food logging and idea deepdive features

- **`HEVY_API_KEY`** — Hevy API key for workout sync
  - Required for workout sync functionality

- **`TAVILY_API_KEY`** — Tavily API key for web research
  - Required for idea deepdive research

## Optional Variables

- **`TIMEZONE`** — Timezone for date/time operations
  - Default: `Asia/Kolkata`
  - Example: `America/New_York`

- **`LLM_MODEL`** — OpenRouter model to use
  - Default: `deepseek/deepseek-chat`

## Legacy Variables (Not Used by Hermes)

The following variables from cere-bro are NOT needed for Hermes:
- `TELEGRAM_BOT_TOKEN` — Hermes gateway handles Telegram
- `TELEGRAM_ALLOWED_USER_ID` — Hermes handles auth
- `BRAVE_SEARCH_API_KEY` — Not currently used

## Example Hermes Configuration

```bash
# ~/.hermes/env or Hermes config file
DB_PATH=/Users/leander/personal-projects/cere-bro/data/cerebro.sqlite
VAULT_ROOT=/Users/leander/personal-projects/cere-bro/vault
OPENROUTER_API_KEY=sk-or-v1-...
HEVY_API_KEY=...
TAVILY_API_KEY=tvly-...
TIMEZONE=Asia/Kolkata
```
