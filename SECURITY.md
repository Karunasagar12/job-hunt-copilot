# Security

Job Hunt Copilot is designed to run on your own computer. The web server binds to `127.0.0.1`, and the app has no login system. Keep that binding in place. Do not change it to `0.0.0.0`, expose the app to the internet, or use it as a multi-user service.

Provider keys and integration credentials are stored in `data/settings.json`; Gmail OAuth files are stored under `data/gmail/`. Keep the entire `data/` folder private, do not commit or share it, and protect backups as you would protect passwords. The repository's `.gitignore` excludes this folder.

The app sends data to the AI provider you configure and to optional services when you use their features. Review each provider's privacy and retention terms before connecting it. Gmail support creates drafts; it does not send mail automatically.

Report a suspected security issue through GitHub's private vulnerability reporting for this repository. Do not include credentials or personal data in a public issue.
