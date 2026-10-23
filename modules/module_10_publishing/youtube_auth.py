"""One-time YouTube login: `python -m modules.module_10_publishing.youtube_auth`

Opens Google's consent screen in your browser and saves an OAuth token (with refresh token) to
YOUTUBE_TOKEN_FILE so uploads work without logging in again.
"""
from __future__ import annotations

import sys
from pathlib import Path

from ..config import get_settings
from .adapters.youtube_publisher import SCOPES


def main() -> int:
    s = get_settings()
    secrets = Path(s.youtube_client_secrets_file) if s.youtube_client_secrets_file else None
    if not secrets or not secrets.exists():
        print("Set YOUTUBE_CLIENT_SECRETS_FILE in .env to the OAuth 'Desktop app' client JSON from Google Cloud Console.")
        return 1
    from google_auth_oauthlib.flow import InstalledAppFlow
    creds = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES).run_local_server(port=0)
    Path(s.youtube_token_file).write_text(creds.to_json())
    print(f"Saved YouTube token to {s.youtube_token_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
