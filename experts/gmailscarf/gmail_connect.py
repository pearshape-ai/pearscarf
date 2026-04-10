"""Gmail API client and tool definitions.

GmailConnect holds the authenticated API client and exposes tools the
LLM agent uses to read, search, and reply to emails. The module-level
`get_tools(ctx)` is what pearscarf calls at startup.

Stub — real implementation in a follow-up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pearscarf.expert_context import ExpertContext


class GmailConnect:
    """Authenticated Gmail client + tool factory."""

    def __init__(self, ctx: ExpertContext) -> None:
        self._ctx = ctx

    def get_tools(self) -> list:
        """Return the list of BaseTool instances for the LLM agent."""
        return []


def get_tools(ctx: ExpertContext) -> GmailConnect:
    """Module-level entry point. Pearscarf calls this at startup."""
    return GmailConnect(ctx)


def run_oauth_flow() -> None:
    """Run the Gmail OAuth2 flow to obtain a refresh token.

    Opens a browser for Google consent, receives the callback, and
    prints the refresh token for the operator to add to .env.
    """
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise SystemExit(
            "google-auth-oauthlib is required for OAuth. "
            "Install with: uv add google-auth-oauthlib"
        )

    from pearscarf import config

    if not config.GMAIL_CLIENT_ID or not config.GMAIL_CLIENT_SECRET:
        raise SystemExit(
            "Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env before running --auth.\n"
            "Get these from Google Cloud Console → APIs & Services → Credentials."
        )

    client_config = {
        "installed": {
            "client_id": config.GMAIL_CLIENT_ID,
            "client_secret": config.GMAIL_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(
        client_config,
        scopes=["https://www.googleapis.com/auth/gmail.modify"],
    )
    creds = flow.run_local_server(port=8080)

    print("\nRefresh token obtained. Add this to your .env:\n")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print("\nOnce added, restart PearScarf to use API-based Gmail access.")
