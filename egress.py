"""The one egress helper the vk module uses: the Accept-Language its
sessions send."""


def accept_language(proxy=None):
    """US English, through a proxy or on a direct connection. VK answers in
    the same language either way; only its own labels (reaction names,
    "views") follow this header."""
    return "en-US,en;q=0.9"
