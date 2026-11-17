"""The one egress helper the vk module uses: the Accept-Language its
sessions send."""


def accept_language(proxy=None):
    """US English, through a proxy or on a direct connection. VK answers in
    the same language either way; only its own labels (reaction names,
    "views") follow this header."""
    return "en-US,en;q=0.9"


ACCEPT_LANGUAGE = "en-US,en;q=0.9"


def exit_proxy(exit=None):
    return exit if exit and "://" in str(exit) else None


def new_session(exit=None, impersonate="chrome", **kw):
    from curl_cffi import requests as curl
    sess = curl.Session(impersonate=impersonate, **kw)
    proxy = exit_proxy(exit)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    return sess
