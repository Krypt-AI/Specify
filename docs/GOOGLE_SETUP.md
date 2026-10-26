# Google Cloud setup

Specify needs one OAuth client. These steps happen manually in the
[Google Cloud Console](https://console.cloud.google.com/). The pages named below (Branding,
Audience, Data Access, Clients) are in the console's **Google Auth Platform** section, which is
also reachable through APIs & Services → OAuth consent screen.

Finish all of the steps before your first sign-in. Their order only matters in one place: enable
the APIs (step 2) before declaring scopes (step 4), because the scope picker lists only scopes of
enabled APIs.

1. **Create a project**, for example `specify`.
2. **Enable the APIs** (APIs & Services → Library): *Gmail API* and *Google Sheets API*.
3. **Set up the consent screen** (Google Auth Platform → Branding and Audience):
   - App name: `Specify`. Use your own email address for the support and developer contacts.
   - Audience: *External*. While the app is in *Testing*, only test users can sign in, so add
     your own Google account under Audience → Test users.
4. **Declare the scopes** (Google Auth Platform → Data Access → *Add or remove scopes*):
   - Tick each scope in the table below. If a scope is not listed, paste its URL into
     *Manually add scopes* at the bottom of the panel.
   - Click *Update*, then *Save* on the Data Access page.
5. **Create the OAuth client** (Google Auth Platform → Clients → Create client):
   - Application type: *Web application*.
   - Authorized JavaScript origins: leave empty. The browser never calls Google directly.
   - Authorized redirect URI: `http://localhost:8000/api/auth/google/callback`
     (in production: `${BACKEND_URL}/api/auth/google/callback`).
   - **Use this client for an AI-powered agent:** leave unticked. Google intends agentic clients for
     AI agents, automated tool execution and MCP integrations. Specify's backend calls Gmail and
     Sheets directly, and the AI model never holds tokens or calls Google, so this is a standard
     client. Google requires a separate agentic client for any future agent or MCP feature.
6. Copy the client ID and secret into `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
   Google shows the full secret only when the client is created. If you lose it, add a new
   secret on the client's page.

## Scopes and why they are needed

Specify requests scopes incrementally. Sign-in asks only for identity, and each integration asks
for its own scopes when you click *Connect* in Specify. Declaring them on the Data Access page
makes the consent screen list them, and Google requires it before it will verify the app.

| Feature | Scope to tick | Reason |
| --- | --- | --- |
| Sign-in | `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile` | Identify you and create your account. |
| Gmail | `https://www.googleapis.com/auth/gmail.modify` | Read messages to classify them, create `Specify/*` labels and apply them to messages, and create reply drafts. |
| Sheets | `https://www.googleapis.com/auth/spreadsheets` | Read and write the tracking spreadsheet you select (used from Phase 4). |

**Why `gmail.modify`.** Applying labels to messages requires it. `gmail.labels` can only manage the
labels themselves. `gmail.modify` also covers reading messages and creating drafts, so Specify needs
no other Gmail scope. It cannot permanently delete mail. No Gmail scope allows drafting without
also allowing sending, so Specify enforces *Draft Only* in its own code and never sends
automatically.

**Why `spreadsheets` rather than `drive.file`.** `drive.file` would only reach a spreadsheet you
choose through Google's browser-based Picker, and the Picker needs an access token in the browser.
Specify keeps every Google token on the server, so it uses `spreadsheets` and opens only the
spreadsheet you select.

## Testing mode limits

- Gmail's `gmail.modify` scope is *restricted* and `spreadsheets` is *sensitive*. In *Testing* mode
  they work for the test users you added.
- In Testing mode, Google expires refresh tokens after 7 days, so Specify will ask you to reconnect
  Gmail about once a week. Publishing the app (Audience → *Publish app*) removes that limit.
  Until Google verifies the app, sign-in then shows an "unverified app" warning, which you can
  click through for your own account. Opening Specify to other people requires Google's
  verification and, for restricted scopes, a security assessment.

Pub/Sub push notifications will add their own setup section here. Until then Specify polls Gmail
on a schedule.
