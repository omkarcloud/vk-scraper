"""Configuration for the VK Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT               port the API listens on (default 8000)
    VK_PROXY           proxy URL for every request, e.g.
                       http://user:pass@host:port (default: none — direct).
                       VK's API answered every call from a plain connection
                       in our tests, so you very likely don't need this.
    VK_FALLBACK_PROXY  proxy new sessions use for VK_BLOCK_HOLD_S seconds
                       after VK rate-limits a request (403 / 429 / its
                       "are you a robot" page) while VK_PROXY is unset
                       (default: none — stays direct and retries).

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# The identity of vk.com's own web client. VK's website ships these to every
# browser and uses them to get an anonymous (logged-out) token, which is all
# the scraper needs — they are public constants, not credentials.
VK_APP_ID = 6287487
VK_APP_SECRET = "QbYic1K3lEV5kTGiqlq2"
VK_ANONYMOUS_SCOPES = "audio_anonymous,video_anonymous,photos_anonymous,profile_anonymous"
VK_API_VERSION = "5.289"          # the API version the web client sends
VK_TOKEN_REFRESH_MARGIN_S = 1800  # get a fresh token this long before the current one expires

VK_BLOCK_HOLD_S = 600      # seconds the fallback proxy is used after a block

VK_PROXY = os.environ.get("VK_PROXY") or None


def vk_proxy():
    """The proxy for one curl session (None = direct)."""
    return os.environ.get("VK_PROXY") or None


def vk_block_proxy():
    """The proxy new sessions use for VK_BLOCK_HOLD_S seconds after a block
    (VK_FALLBACK_PROXY, else VK_PROXY, else direct)."""
    return os.environ.get("VK_FALLBACK_PROXY") or os.environ.get("VK_PROXY") or None
