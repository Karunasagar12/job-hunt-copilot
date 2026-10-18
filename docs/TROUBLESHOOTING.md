# Troubleshooting

## Docker is not running

Open Docker Desktop and wait until its engine is running. Then double-click the start script again. If Docker Desktop reports an error, use its troubleshooting menu before restarting Job Hunt Copilot.

## Port 8080 is in use

Another app is using the local web address. Stop that app, or open `docker-compose.yml` in a text editor and change the port line to:

```yaml
      - "127.0.0.1:8081:8080"
```

Save the file, run the start script, and open [http://127.0.0.1:8081](http://127.0.0.1:8081).

## The PDF looks like an image

Some source CV PDFs contain scanned pages instead of selectable text. Upload a text-based PDF or a DOCX file. If the extracted information is incomplete, answer the setup questions and review every drafted detail before saving.

## The API key was rejected

Open Settings, replace the key, and select **Test**. Check that the key belongs to the selected provider, has not expired, and that the provider account permits API use. Do not paste a key into a public issue or chat.

## Mac says the file is from an unidentified developer

In Finder, right-click `start.command`, choose **Open**, and confirm **Open** in the dialog. This is normally needed only the first time.

## Apple Silicon Mac

The Docker image is built for both Intel/AMD and Apple Silicon Macs. Ensure Docker Desktop is up to date, then try the start script again.

## Find the logs

In Docker Desktop, open **Containers**, select `job-hunt-copilot`, then select the `app` or `scheduler` container and open **Logs**. Include the relevant error text when asking for help, but remove personal data and secrets first.

## Reset everything

Stop the app first. Make a backup if you may need your applications later. Then delete the `data` folder next to the start script. Starting the app again creates fresh data and begins setup again. This permanently removes the local profile, settings, application history, uploads, and generated files.

## Still stuck?

Check the setup and provider guides under [Integrations](integrations/anthropic.md), then open an issue on GitHub without including API keys, CVs, or other personal data.
