# Gmail (advanced)

## What it unlocks

Gmail lets Job Hunt Copilot prepare and check application email drafts in your Google account. It is drafts-only: the app does not send mail for you.

## Cost

Gmail API access has no separate per-request charge for this use, but Google Cloud account terms and limits apply. See [Google Cloud pricing](https://cloud.google.com/pricing).

## Get Google OAuth credentials

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and create a project.
2. Select the project, open **APIs & Services → Library**, find **Gmail API**, and enable it.
3. Open **Google Auth Platform** (or **APIs & Services → OAuth consent screen**) and configure the consent screen. Choose **External** if asked, add your own Google account as a test user, and complete the required app information. Keep the app in testing for personal use.
4. Open **Clients** or **Credentials**, choose **Create OAuth client ID**, and select **Web application**.
5. Add this exact authorized redirect URI: `http://localhost:8080/api/gmail/callback`.
6. Create the client and download its JSON credentials file. Keep the file private.

Google's console labels may change. Use Google's [OAuth setup guide](https://developers.google.com/workspace/guides/configure-oauth-consent) if the menu names differ.

## Connect it

Open Settings, choose the Gmail card, upload the downloaded JSON file, and select **Connect Gmail**. A Google sign-in window opens. Review the requested access, then return to Job Hunt Copilot and test the connection. The app stores OAuth credentials in `data/gmail/`. Do not share or commit that folder.
