# Run AI SDR on another computer

GitHub holds the code. The dashboard runs locally on the computer where you start it; computers do not automatically share database changes. Email delivery is still simulated. Salesforce is not connected.

## 1. Get the latest code

Install Git and Python 3.11. Sign in to GitHub as an account with access to the private repository. In Terminal:

```sh
git clone https://github.com/nandaagastya/ai_sdr.git
cd ai_sdr
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, use `py -3.11 -m venv .venv`, then `.venv\Scripts\Activate.ps1` in PowerShell instead of `source`.

## 2. Restore your private data and settings

Transfer the separately prepared `private-transfer` folder directly between your devices using AirDrop, an encrypted USB drive, or another private transfer method. Do not upload it to GitHub or send its contents in chat. It contains API keys and lead data.

Before starting the app, copy its `.env` file to the project root, and its `ai_sdr.db` file to `instance/ai_sdr.db`. Hidden files may need to be shown to see `.env`. Create the `instance` folder if it does not exist. **Do not overwrite an existing database or configuration**; back up any existing installation first. The transfer README identifies the snapshot date and original database location.

Set `DATABASE_URL=sqlite:///ai_sdr.db` in the laptop's `.env` so Flask uses the restored database under `instance/`. Other API keys can be retained from the privately transferred configuration. Do not copy the old `.venv`; install a fresh environment as above.

If you only want an empty installation, copy `.env.example` to `.env` instead and configure your own values. The app creates empty tables at startup.

**Never run `seed.py`: it deletes existing data.**

## 3. Verify and start

```sh
python -m unittest discover -s tests -q
python -m flask --app run:app run --host 127.0.0.1 --port 5001
```

Open http://127.0.0.1:5001 in your browser. Check your lead totals and saved previews against the old computer. The test suite uses test databases; it does not verify that you restored your personal records. Keep the original computer's database until you have checked the restored copy.

Leave the terminal running while using the app. Press Ctrl+C to stop. This is a local development application with no login: keep it bound to 127.0.0.1. No hosting subscription is required.

## 4. Continue work later

Use `git pull --ff-only` to download newer code when your working tree is clean. Database records and `.env` settings are intentionally ignored by Git. Choose one computer as your active source of data; never attempt to merge SQLite files using Git. To move data again, stop app writes and make a new consistent SQLite backup.
