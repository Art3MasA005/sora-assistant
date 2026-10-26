# Google setup

বাংলা গাইড: [google-setup.bn.md](google-setup.bn.md)

This lets the **Connect Google** button work. You create your own OAuth app once. Google never reviews it, because you are its only user.

## 1. Create a Google Cloud project

1. Open <https://console.cloud.google.com/> and create a project, e.g. `sora-assistant`.
2. **APIs & Services → Library**. Enable each of these:
   - Gmail API
   - Google Calendar API
   - Google Drive API
   - Google Docs API
   - Google Sheets API
   - Google Slides API
   - Google Tasks API
   - People API

## 2. OAuth consent screen

1. **APIs & Services → OAuth consent screen** (also called "Google Auth Platform"). Fill in these fields:
   - User type: **External**
   - App name: `Sora`
   - Support email and developer email: your address
2. Under **Audience**, add your own Gmail address as a test user.
3. **Publish the app** so its status is **In production**. Do not send it for verification.

> ⚠️ An app left in **Testing** status issues refresh tokens that expire after **7 days**. You would then have to reconnect every week. An app **In production** but unverified keeps its tokens. It only shows an "unverified app" warning when you connect. Click **Advanced → Go to Sora (unsafe)**. This is safe because it is your own app.

You don't need to declare scopes on the consent screen. Sora requests them when you connect.

## 3. Create the OAuth client

1. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. Application type: **Web application**.
3. Under **Authorized redirect URIs**, add exactly the URI Sora uses: `{PUBLIC_BASE_URL}/oauth/google/callback`.
   - On this PC only: `http://localhost:8000/oauth/google/callback`
   - From your phone through Tailscale: `https://<your-pc>.<tailnet>.ts.net/oauth/google/callback` (see below)
   - You can add both.
4. Copy the client ID and client secret into `.env`:
   ```
   GOOGLE_CLIENT_ID=....apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=GOCSPX-...
   ```
   Never commit these values. Never download `client_secret.json` into the repo.

## 4. Connect

Restart the server. Then run `python -m sora connect-google` (or tap **Connect Google** in the app, which calls `POST /api/connections/google/start`). Approve the permissions. The page says "Google connected".

Sora asks for these permissions:

| Scope | Used for |
|---|---|
| `gmail.modify` | Reading, searching, sending, replying, drafts, labels, trash (Sora never permanently deletes mail) |
| `calendar` | Reading and editing events |
| `drive` | Searching and reading files; covers Docs, Sheets and Slides too |
| `tasks` | Google Tasks |
| `contacts.readonly`, `contacts.other.readonly` | Looking up email addresses by name |

## Reaching the server from your phone (Tailscale)

Google only accepts `http://` redirects for `localhost`. To connect from the phone, use HTTPS through Tailscale:

1. Install [Tailscale](https://tailscale.com/download) on the PC and on the phone. Sign in to the same account on both.
2. In the Tailscale admin console, turn on **MagicDNS** and **HTTPS certificates**.
3. On the PC, run `tailscale serve --bg 8000`. The server is now at `https://<pc-name>.<tailnet>.ts.net`, and only your devices can reach it.
4. In `.env`, set `PUBLIC_BASE_URL` to that URL. Add `<that URL>/oauth/google/callback` to the OAuth client's redirect URIs.
