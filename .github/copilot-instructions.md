# Copilot / AI Agent Instructions for AVAOperationLog

Purpose: Help an AI coding agent become immediately productive editing and testing this repository.

Quick architecture & intent
- Single-file Streamlit web app: `AVAOperationLog.py` is the primary entrypoint and implements the whole UI and business logic.
- Purpose: interactive exploration and filtering of Avaplace operation logs (server-side filtering, lazy-loading of OperationID history, Sankey/time visualizations).
- Credentials: the app writes a local `avaplace_credentials.json` (hardware-bound, encrypted). Do NOT commit or attempt to migrate decrypted credentials.

Key files to inspect
- `AVAOperationLog.py` — UI, API calls, filters, and visualization generation. Start here for any behavior change.
- `README.md` — high-level overview and run instructions (Czech). Use it to capture expected user flows.
- `requirements.txt` — dependency list; keep in sync when adding libs.
- `run_test.bat` — Windows convenience runner for local manual testing.
- `Dockerfile`, `docker-compose.yml` — containerized build/run options.

Common workflows (commands)
- Local dev (fast):
  - `pip install -r requirements.txt` (or `pip install streamlit pandas plotly requests`)
  - `streamlit run AVAOperationLog.py`
- Windows quick-run: double-click `run_test.bat` or run it from cmd.
- Docker (build & run):
  - `docker build -t avaoperationlog .`
  - `docker-compose up --build`

Project-specific patterns and constraints
- Single-file design: prefer small, focused edits inside `AVAOperationLog.py` rather than large refactors — keep changes minimal and test UI flows.
- Server-side filtering: API calls include filters (dates, severity, AgentID, SourceID). When changing data-fetch logic, verify filters are preserved and pagination/lazy-load still works.
- Lazy-loading of operation history: clicking a master-row triggers detailed history fetch for that `OperationID`. Preserve this interaction when editing UI or data fetching.
- Sankey/time visualizations: changes to data shape (column names, grouping) will break Plotly visuals. Run the app and verify Sankey and timeline render correctly after data changes.
- Credentials: `avaplace_credentials.json` is machine-specific and encrypted. Agents must never attempt to include or simulate real credentials in commits or examples.

Testing and verification for agents
- No automated tests detected. Manual verification steps:
  1. Install deps and run `streamlit run AVAOperationLog.py`.
  2. Use the environment switcher and filters to exercise API calls and lazy-loading.
  3. Click an operation to ensure history loads and visualizations update.
  4. Confirm `avaplace_credentials.json` is still in `.gitignore` and not staged.

Commit / PR guidance
- Keep PRs small and focused. For UI/behavior changes include screenshots or short GIFs showing before/after flows.
- Update `requirements.txt` if you add dependencies; prefer pinning minimal versions.
- Add a short note in `README.md` (or translate) for any user-facing changes.

When in doubt
- Read `AVAOperationLog.py` to discover UI callbacks and where API requests are formed.
- Use the `streamlit run` workflow locally to iterate quickly.
- If adding tests, include a small runnable example (pytest or script) and document how to run it in the README.

If anything here is unclear or you want me to expand an area (e.g., mapping of UI callbacks to functions inside `AVAOperationLog.py`, or a Docker test harness), tell me which part to prioritize.
