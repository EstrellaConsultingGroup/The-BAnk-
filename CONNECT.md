# Connecting accounts: what to click

Keys go in `.env` (created by `./setup.sh` from `.env.example`). Never paste a key into chat. If you
did by accident, rotate that key.

## 1. Composio (YouTube + Instagram, Apify optional)

1. Sign up at **platform.composio.dev** and create a project.
2. **Settings → API Keys → Create** → copy it into `.env` as `COMPOSIO_API_KEY=`.
3. **Auth Configs → Create Auth Config → YouTube → "Use Composio managed auth" → Create.**
   Do the same for **Instagram** (and **Apify** if you want Apify connected through Composio too).
4. Back in the terminal/agent: `python -m pipeline connect youtube` prints a link. Open it and sign in with
   the Google account that owns your channel. Repeat with `connect instagram`.
5. Check: `python -m pipeline doctor` should show `composio/youtube: ACTIVE`.

Instagram needs a **Professional (Creator or Business) account linked to a Facebook Page**. In the
Instagram app: Settings → Account type and tools → Switch to professional account, then link a Page in
Meta Business Suite. If Composio's Instagram tool asks for a public video URL instead of an upload, set
`publish.routes.instagram: upload_post` in config.yaml and connect Instagram in Upload-Post instead.

## 2. Upload-Post (TikTok)

1. Sign up at **upload-post.com**.
2. **Manage Users → Add user** (this is your profile name, e.g. your channel name) → **Connect TikTok** and
   approve in TikTok.
3. **API Keys → Create** → `.env`: `UPLOAD_POST_API_KEY=` and `UPLOAD_POST_USER=<that profile name>`.

## 3. Apify (scraping YouTube channels, TikTok, Kick)

1. Sign up at **console.apify.com**.
2. **Settings → Integrations → Personal API tokens** → copy into `.env` as `APIFY_TOKEN=`.
3. The actors used are in `config.yaml → apify`. Open each in the Apify Store once to confirm it exists
   and check its pricing. Add a Kick clips actor id if you want Kick.

## 4. Twitch (optional but recommended for Twitch clips — free)

1. **dev.twitch.tv/console → Register Your Application.** Name: anything. OAuth Redirect URL:
   `http://localhost`. Category: Analytics Tool. Client type: Confidential.
2. **Manage → New Secret.** Put both in `.env`: `TWITCH_CLIENT_ID=`, `TWITCH_CLIENT_SECRET=`.

## 5. Thumbnails (pick one, optional)

- gpt-image: **platform.openai.com → API keys** → `OPENAI_API_KEY=`, set `thumbnails.provider: openai`.
- Nano Banana Pro: **aistudio.google.com → Get API key** → `GEMINI_API_KEY=`, set `thumbnails.provider: gemini`.
- No key: `thumbnails.provider: frame` uses a real frame from the video with big text drawn on it.

## 6. Streamer permission (needed before any clip is rendered)

For each streamer you clip, add them to `streamers.yaml` with `permission: campaign` (they run a paid
clipping campaign — find these on Whop "Content Rewards" and similar clipping platforms) or
`permission: written` (they said yes; keep the proof link). The daily clip run lists the top uncleared
streamers so you know who to ask.

## 7. Cloud sessions

If you run this in Claude Code on the web, the container is fresh each session: `./setup.sh` must run
first (add it to the environment's setup script), and the `.env` values are better stored as environment
secrets than as a file. State is committed to git after every run so nothing is lost.
