"""VK transport: plain curl_cffi with browser-impersonated TLS against VK's
own web API, authenticated with the anonymous token the vk.com web client
mints for logged-out visitors. No login, no cookies, no browser.

Egress: the pod's own IP by default (config.vk_proxy(), knob VK_EXIT) —
every surface passed from the pod on 2026-11-03 (table in config.py). A
retryable failure drops the thread's session; a block (403 / 429 / a
challenge page / VK's rate-limit error codes) also puts the thread's next
sessions on the fallback exit (config.vk_block_proxy()) for
config.VK_BLOCK_HOLD_S seconds.

Upstream surfaces:

  * TOKEN   POST login.vk.ru/?act=get_anonym_token {client_id, client_secret,
            scopes, version, app_id} -> {"type": "okay", "data":
            {"access_token": "anonym.<jwt>", "expired_at": <epoch>}}. The
            token lives 24 h, is bound to the app (not the exit) and is held
            process-wide; API error 5 (auth failed) re-mints it.

  * API     POST web.api.vk.ru/method/<method>?v=5.289&client_id=6287487,
            form body = params + access_token -> {"response": …} |
            {"error": {"error_code", "error_msg", …}}. Methods used: see the
            fetch_* functions. HTTP is 200 even for API errors; the error
            codes are mapped below.

  * ARTICLE GET vk.ru/@<owner-slug> — the only server-rendered page: the
            article body as HTML plus a schema.org Article ld+json block.
            Unknown slugs answer a real HTTP 404.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  VkUpstreamError  transport failure / 5xx / VK internal error        — retryable
  VkBlocked        403 / 429 / challenge page / VK rate-limit codes   — retryable
  VkBadRequest     VK error 100 (bad parameter)                       — never retried
  VkNotFound       unknown / deleted / private object (reason set)    — never retried
"""
import json
import os
import re
import sys
import threading
import time

# Allow direct execution (python vk/fetch.py): flat imports resolve like
# under the server. Idempotent when imported normally.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

IMPERSONATE = "chrome"
API = "https://web.api.vk.ru"
LOGIN = "https://login.vk.ru"
SITE = "https://vk.ru"          # the page host (vk.com redirects here)
API_TIMEOUT = 30
WALL_SEARCH_TIMEOUT = 60
PAGE_TIMEOUT = 30

# Origin / referer as the web client sends them; Accept-Language is set per
# session from its exit (egress.accept_language).
API_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "origin": SITE,
    "referer": SITE + "/",
}
PAGE_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "referer": SITE + "/",
    "upgrade-insecure-requests": "1",
}

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_CHALLENGE_MARKERS = ("challenge.html", "hash429", "что вы не робот", "captcha")

# VK API error codes (dev.vk.com/reference/errors) grouped by what the API
# should do with them.
_ERR_TOKEN = {5}                         # "User authorization failed" -> re-mint the anonymous token
_ERR_RATE = {6, 9, 29}                   # too many requests / flood / rate limit
_ERR_CAPTCHA = {14}
_ERR_BAD_PARAM = {100, 101, 113, 125}    # 113 "invalid user id" is a malformed id, 125 invalid group id
_ERR_NOT_FOUND = {15, 18, 30, 203, 204, 220}   # access denied / deleted / private / group access
_ERR_TRANSIENT = {1, 10}                 # unknown / internal server error


class VkUpstreamError(UpstreamError):
    """Transport failure, 5xx or a VK internal error — retryable."""


class VkBlocked(VkUpstreamError, Blocked):
    """403 / 429, a challenge page where JSON/HTML was expected, or VK's
    rate-limit / captcha error codes — retryable on a fresh exit."""


class VkBadRequest(BadRequest):
    """VK rejected a parameter (error 100 family) — never retried."""


class VkNotFound(NotFound):
    """Unknown, deleted or private object — never retried. `reason` is one
    of unknown / deleted / banned / private / disabled, `details` names the
    object; route_glue puts both in the 404 body."""

    def __init__(self, message, reason="unknown", **details):
        super().__init__(message)
        self.reason = reason
        self.details = details


# ---- sessions ----------------------------------------------------------------
# One session per cheroot worker thread: a curl handle must not be shared
# across threads. The calls are stateless (the token travels in the body),
# so thread-lifetime sessions with keep-alive are enough.
_local = threading.local()
_hold = {"until": 0.0}   # process-wide: a block anywhere moves every NEW session to the fallback exit


def _proxy_for_new_session():
    if time.time() < _hold["until"]:
        return config.vk_block_proxy()
    return config.vk_proxy()


def _session():
    sess = getattr(_local, "session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        proxy = _proxy_for_new_session()
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        sess.headers["accept-language"] = egress.accept_language(proxy)
        _local.session = sess
    return sess


def _drop_session():
    """Close the thread's session so a poisoned keep-alive connection dies
    and the next call opens a fresh exit."""
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _note_block():
    _hold["until"] = time.time() + config.VK_BLOCK_HOLD_S


def _retrying(fn):
    """Run fn() under the shared retry policy (VkUpstreamError only;
    NotFound / BadRequest surface immediately)."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except VkUpstreamError as e:
            last = e
            if isinstance(e, VkBlocked):
                _note_block()
            _drop_session()
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def _looks_like_challenge(text, url=""):
    head = (text or "")[:4000].lower()
    return "challenge.html" in (url or "") or any(m in head for m in _CHALLENGE_MARKERS)


# ---- the anonymous token -------------------------------------------------------
_token_lock = threading.Lock()
_token = {"value": None, "expires": 0.0}


def _mint_token():
    """POST the web client's anonymous-token request. Returns (token, expires)."""
    try:
        resp = _session().post(f"{LOGIN}/?act=get_anonym_token", data={
            "client_id": config.VK_APP_ID,
            "client_secret": config.VK_APP_SECRET,
            "scopes": config.VK_ANONYMOUS_SCOPES,
            "version": 1,
            "app_id": config.VK_APP_ID,
        }, headers=API_HEADERS, timeout=API_TIMEOUT)
    except Exception as e:
        raise VkUpstreamError(f"token request failed: {type(e).__name__}: {e}")
    if resp.status_code in (401, 403, 429):
        raise VkBlocked(f"HTTP {resp.status_code} from the token mint")
    if resp.status_code != 200:
        raise VkUpstreamError(f"HTTP {resp.status_code} from the token mint")
    try:
        payload = resp.json()
    except Exception:
        raise VkBlocked(f"non-JSON token response: {resp.text[:120]!r}")
    data = payload.get("data") if isinstance(payload, dict) else None
    token = (data or {}).get("access_token")
    if payload.get("type") != "okay" or not token:
        raise VkUpstreamError(f"token mint refused: {json.dumps(payload)[:200]}")
    expires = data.get("expired_at") or (time.time() + 24 * 3600)
    return token, float(expires)


def get_token(force=False):
    """The process-wide anonymous token, minted on first use and re-minted
    VK_TOKEN_REFRESH_MARGIN_S before it expires (or on force)."""
    with _token_lock:
        fresh = _token["value"] and time.time() < _token["expires"] - config.VK_TOKEN_REFRESH_MARGIN_S
        if fresh and not force:
            return _token["value"]
        token, expires = _retrying(_mint_token)
        _token["value"], _token["expires"] = token, expires
        return token


def _invalidate_token(token):
    with _token_lock:
        if _token["value"] == token:
            _token["value"], _token["expires"] = None, 0.0


# ---- API calls -----------------------------------------------------------------

def _raise_api_error(error, label):
    code = error.get("error_code")
    msg = (error.get("error_msg") or "").strip()
    low = msg.lower()
    if code in _ERR_RATE:
        raise VkBlocked(f"VK rate limit on {label}: {msg}")
    if code in _ERR_CAPTCHA:
        raise VkBlocked(f"VK asks for a captcha on {label}")
    if code in _ERR_BAD_PARAM:
        if code in (113, 125):
            raise VkNotFound(f"{label}: {msg}", reason="unknown")
        raise VkBadRequest(msg or f"VK rejected the parameters of {label}")
    if code in _ERR_NOT_FOUND:
        if "deleted" in low:
            reason = "deleted"
        elif "banned" in low or "blocked" in low:
            reason = "banned"
        elif "private" in low or "hid" in low or "closed" in low or code in (30, 203):
            reason = "private"
        elif "disabled" in low:
            reason = "disabled"
        else:
            reason = "unavailable"
        raise VkNotFound(f"{label}: {msg or 'not available'}", reason=reason)
    if code in _ERR_TRANSIENT:
        raise VkUpstreamError(f"VK error {code} on {label}: {msg}")
    raise VkUpstreamError(f"VK error {code} on {label}: {msg}")


def call(method, params, label=None, timeout=API_TIMEOUT):
    """POST one API method with the anonymous token -> the `response` value.
    API errors are mapped to the taxonomy; an expired token is re-minted and
    the call retried under the shared ladder."""
    label = label or method
    clean = {k: v for k, v in params.items() if v is not None}

    def once():
        token = get_token()
        url = f"{API}/method/{method}?v={config.VK_API_VERSION}&client_id={config.VK_APP_ID}"
        try:
            resp = _session().post(url, data={**clean, "access_token": token},
                                   headers=API_HEADERS, timeout=timeout)
        except Exception as e:
            raise VkUpstreamError(f"request failed: {type(e).__name__}: {e}")
        if resp.status_code in (401, 403, 429):
            raise VkBlocked(f"HTTP {resp.status_code} on {label}")
        if resp.status_code != 200:
            raise VkUpstreamError(f"HTTP {resp.status_code} on {label}")
        try:
            payload = resp.json()
        except Exception:
            raise VkBlocked(f"non-JSON API response on {label}: {resp.text[:120]!r}")
        if not isinstance(payload, dict):
            raise VkUpstreamError(f"unexpected API payload on {label}: {str(payload)[:120]!r}")
        error = payload.get("error")
        if isinstance(error, dict):
            if error.get("error_code") in _ERR_TOKEN:
                _invalidate_token(token)
                raise VkUpstreamError(f"anonymous token refused on {label}: {error.get('error_msg')}")
            _raise_api_error(error, label)
        if "response" not in payload:
            raise VkUpstreamError(f"API payload without response on {label}")
        return payload["response"]
    return _retrying(once)


# ---- method wrappers (raw responses; vk/parsers.py shapes them) ------------------

USER_FIELDS = ("about,activities,bdate,books,can_access_closed,can_post,can_see_all_posts,"
               "can_write_private_message,career,city,country,cover,deactivated,domain,education,"
               "followers_count,games,has_photo,home_town,interests,is_closed,is_nft,last_seen,"
               "maiden_name,military,movies,music,nickname,occupation,online,personal,photo_100,"
               "photo_200,photo_50,photo_400_orig,photo_id,photo_max,photo_max_orig,quotes,relation,"
               "relatives,schools,screen_name,sex,site,status,trending,tv,universities,verified,"
               "wall_default,wall_comments")
CARD_FIELDS = ("photo_50,photo_100,photo_200,screen_name,verified,is_closed,can_access_closed,"
               "deactivated,sex,city,country,bdate,online,last_seen,followers_count,domain")
GROUP_FIELDS = ("activity,addresses,age_limits,ban_info,can_see_all_posts,city,contacts,counters,"
                "country,cover,crop_photo,deactivated,description,finish_date,fixed_post,has_photo,"
                "is_closed,is_government_organization,links,main_section,market,members_count,"
                "members_count_text,menu,photo_50,photo_100,photo_200,photo_max_orig,place,"
                "public_date_label,screen_name,secondary_section,site,start_date,status,trending,"
                "type,verified,wall,wiki_page")
GROUP_CARD_FIELDS = "photo_50,photo_100,photo_200,screen_name,verified,is_closed,type,members_count,activity,deactivated"
COMMENT_AUTHOR_FIELDS = "photo_50,photo_100,screen_name,verified,is_closed,deactivated"


def fetch_resolve_screen_name(screen_name):
    """utils.resolveScreenName -> {"object_id", "type"} | [] when unknown."""
    return call("utils.resolveScreenName", {"screen_name": screen_name}, f"screen name {screen_name}")


def fetch_user(user):
    """users.get for one id / screen name -> the raw list (one element)."""
    return call("users.get", {"user_ids": user, "fields": USER_FIELDS}, f"user {user}")


def fetch_community(community):
    """groups.getById for one id / screen name -> {"groups": [..], "profiles": [..]}."""
    return call("groups.getById", {"group_ids": community, "fields": GROUP_FIELDS}, f"community {community}")


def fetch_community_addresses(group_id):
    return call("groups.getAddresses", {
        "group_id": group_id, "count": 100,
        # `city` / `country` (objects with titles) rather than the *_id fields
        "fields": "title,address,additional_address,city,country,metro_station,latitude,"
                  "longitude,work_info_status,timetable,phone,time_offset",
    }, f"addresses of community {group_id}")


def fetch_wall(owner_id, offset, count, post_filter="all"):
    return call("wall.get", {"owner_id": owner_id, "offset": offset, "count": count,
                             "filter": post_filter, "extended": 1, "fields": CARD_FIELDS},
                f"wall of {owner_id}")


def fetch_wall_search(owner_id, query, offset, count, owners_only=True):
    """wall.search is VK's slowest method: 2-3 s with owners_only, 7-60 s
    (and an occasional error 10 "Internal server error") without, measured
    2026-11-03 on large walls; a successful answer took 34 s, so it gets a
    longer timeout than the other calls."""
    return call("wall.search", {"owner_id": owner_id, "query": query, "offset": offset, "count": count,
                                "owners_only": 1 if owners_only else 0, "extended": 1,
                                "fields": CARD_FIELDS}, f"post search on {owner_id}",
                timeout=WALL_SEARCH_TIMEOUT)


def fetch_post(owner_id, post_id):
    return call("wall.getById", {"posts": f"{owner_id}_{post_id}", "extended": 1,
                                 "copy_history_depth": 2, "fields": CARD_FIELDS},
                f"post {owner_id}_{post_id}")


def fetch_post_comments(owner_id, post_id, offset, count, sort="asc", comment_id=None):
    return call("wall.getComments", {
        "owner_id": owner_id, "post_id": post_id, "offset": offset, "count": count, "sort": sort,
        "comment_id": comment_id, "need_likes": 1, "extended": 1, "thread_items_count": 10,
        "fields": COMMENT_AUTHOR_FIELDS,
    }, f"comments of post {owner_id}_{post_id}")


def fetch_followers(user_id, offset, count):
    return call("users.getFollowers", {"user_id": user_id, "offset": offset, "count": count,
                                       "fields": CARD_FIELDS}, f"followers of user {user_id}")


def fetch_members_preview(group_id, count=8):
    """groups.getMembers: an anonymous token may read at most 8 members and
    no offset (VK error 100 beyond that), so this is a preview only."""
    return call("groups.getMembers", {"group_id": group_id, "count": count, "fields": CARD_FIELDS},
                f"members of community {group_id}")


def fetch_videos(owner_id, offset, count):
    return call("video.get", {"owner_id": owner_id, "offset": offset, "count": count, "extended": 1},
                f"videos of {owner_id}")


def fetch_video(owner_id, video_id):
    return call("video.get", {"videos": f"{owner_id}_{video_id}", "extended": 1},
                f"video {owner_id}_{video_id}")


def fetch_video_comments(owner_id, video_id, offset, count, sort="desc"):
    return call("video.getComments", {
        "owner_id": owner_id, "video_id": video_id, "offset": offset, "count": count, "sort": sort,
        "need_likes": 1, "extended": 1, "fields": COMMENT_AUTHOR_FIELDS,
    }, f"comments of video {owner_id}_{video_id}")


def fetch_clips(owner_id, count, start_from=None):
    return call("shortVideo.getOwnerVideos", {"owner_id": owner_id, "count": count,
                                              "start_from": start_from}, f"clips of {owner_id}")


def fetch_photos(owner_id, album, offset, count):
    """photos.getAll for album="all", else photos.get on the album id
    (wall / profile / saved / a numeric album id)."""
    if album == "all":
        return call("photos.getAll", {"owner_id": owner_id, "offset": offset, "count": count,
                                      "extended": 1, "photo_sizes": 1}, f"photos of {owner_id}")
    return call("photos.get", {"owner_id": owner_id, "album_id": album, "offset": offset, "count": count,
                               "rev": 1, "extended": 1, "photo_sizes": 1}, f"photos of {owner_id} ({album})")


def fetch_articles(owner_id, offset, count):
    return call("articles.getOwnerPublished", {"owner_id": owner_id, "offset": offset, "count": count},
                f"articles of {owner_id}")


def fetch_community_search(query, count, sort=None, community_type=None):
    return call("catalog.getSearchGroups", {"q": query, "count": count, "sort": sort, "type": community_type,
                                            "need_blocks": 1}, f"community search {query!r}")


def fetch_video_search(query, count, sort=None, content_type=None, duration=None, hd=None):
    return call("catalog.getVideoSearch", {"q": query, "count": count, "sort": sort,
                                           "content_type": content_type, "duration": duration,
                                           "hd": 1 if hd else None, "need_blocks": 1},
                f"video search {query!r}")


def fetch_catalog_section(section_id, start_from, count):
    """The next page of a catalog search (section id + next_from of the
    previous page)."""
    return call("catalog.getSection", {"section_id": section_id, "start_from": start_from, "count": count},
                "catalog page")


# ---- the article page ------------------------------------------------------------

def fetch_article_page(slug):
    """GET vk.ru/@<slug> -> the HTML. A missing article is a real 404; a
    challenge page or an empty shell is a block."""
    def once():
        try:
            resp = _session().get(f"{SITE}/@{slug}", headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT)
        except Exception as e:
            raise VkUpstreamError(f"request failed: {type(e).__name__}: {e}")
        if resp.status_code == 404:
            raise VkNotFound(f"article @{slug} not found", reason="unknown", article=slug)
        if resp.status_code in (401, 403, 429):
            raise VkBlocked(f"HTTP {resp.status_code} for article @{slug}")
        if resp.status_code != 200:
            raise VkUpstreamError(f"HTTP {resp.status_code} for article @{slug}")
        text = resp.text
        if _looks_like_challenge(text, str(resp.url)):
            raise VkBlocked(f"challenge page for article @{slug}")
        if 'id="article_view_' not in text:
            raise VkBlocked(f"article @{slug} answered without its body (shell page)")
        return text
    return _retrying(once)
