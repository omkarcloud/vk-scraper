"""Reference resolvers, link builders and the choice tables for /vk/*.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url` / `id` pair). Each resolver takes the raw query string and returns a
plain JSON-able value (the cache key is built from the validated params),
raising ValueError with a user-facing message (RefField -> 400):

  * user       numeric id (1), "id1", a screen name ("durov") or any
               vk.com / vk.ru / m.vk.com profile link
               -> {"id": 1, "screen_name": None} | {"id": None, "screen_name": "durov"}
  * community  numeric id (22822305, "-22822305"), "club22822305" /
               "public…" / "event…", a screen name ("vk") or a community link
               -> same shape; the id is the POSITIVE group id
  * post       "-22822305_1736006", "wall-22822305_1736006" or any post link
               (vk.com/wall-22822305_1736006, …?w=wall-22822305_1736006)
               -> {"owner_id": -22822305, "post_id": 1736006}
  * video      "-22822305_456243154", "video-…", "clip-…", a vk.com / vkvideo.ru
               video or clip link, or a video_ext.php?oid=…&id=… embed link
               -> {"owner_id": -22822305, "video_id": 456243154}
  * article    "@vk-verify" (or "vk-verify") or a vk.com/@vk-verify link
               -> "vk-verify"

Identifier shapes (VK): a user is a positive id, a community a negative
owner_id (the group id negated); every object link is <owner_id>_<item_id>.
Screen names are 2-32 chars of [A-Za-z0-9_.]; "id<N>", "club<N>",
"public<N>", "event<N>" are the numeric aliases VK itself serves.

Public links are built on vk.com (VK's international domain; it redirects
to vk.ru, which the site made its primary domain in 2025); videos also get
their vkvideo.ru link from the API.
"""
import re
from urllib.parse import parse_qs, urlparse

SITE = "https://vk.com"
VIDEO_SITE = "https://vkvideo.ru"

_VK_HOSTS = ("vk.com", "vk.ru", "vkvideo.ru", "vkontakte.ru")

SCREEN_NAME_RE = re.compile(r"^[A-Za-z0-9_.]{2,32}$")
_NUMERIC_ALIAS_RE = re.compile(r"^(id|club|public|event)(\d{1,12})$", re.I)
_OBJECT_RE = re.compile(r"^(-?\d{1,12})_(\d{1,12})$")
_WALL_RE = re.compile(r"wall(-?\d{1,12})_(\d{1,12})")
_VIDEO_RE = re.compile(r"(?:video|clip)(-?\d{1,12})_(\d{1,12})")
_ARTICLE_RE = re.compile(r"^@?([A-Za-z0-9_.]+-[A-Za-z0-9_.-]+)$")

# path segments of vk.com that are sections, never a profile
_RESERVED_PATHS = {
    "feed", "im", "friends", "groups", "video", "videos", "clips", "music", "audio", "market",
    "search", "people", "login", "join", "wall", "photos", "albums", "settings", "support",
    "faq", "terms", "privacy", "about", "dev", "apps", "games", "calls", "mail", "stories",
    "docs", "bookmarks", "fave", "ads", "business", "catalog", "topic", "board", "events",
    "places", "donut", "article", "articles", "podcasts", "live", "video_ext.php", "away.php",
}


def _split_link(value):
    """A vk link -> (host, path, query dict) or None when it is not a link."""
    value = (value or "").strip()
    if value.startswith("//"):
        value = "https:" + value
    if re.match(r"^(m\.|www\.)?(vk\.com|vk\.ru|vkvideo\.ru)/", value, re.I):
        value = "https://" + value
    if not value.startswith(("http://", "https://")):
        return None
    parts = urlparse(value)
    host = (parts.hostname or "").lower()
    for root in _VK_HOSTS:
        if host == root or host.endswith("." + root):
            break
    else:
        raise ValueError("Must be a vk.com link.")
    return host, parts.path, parse_qs(parts.query)


def _owner_from_path(path, query):
    """The profile / community segment of a vk link: 'durov', 'id1', 'club1',
    'vk'. Links to a post / video / article are not profiles."""
    segment = path.strip("/").split("/")[0] if path.strip("/") else ""
    segment = segment.split("?")[0]
    if segment.startswith("@"):
        segment = segment[1:]
    if "z" in query or "w" in query:
        # vk.com/durov?w=wall1_2 is still Durov's page; the object link forms
        # are handled by the post / video resolvers
        pass
    if not segment or segment.lower() in _RESERVED_PATHS or _WALL_RE.match(segment) \
            or _VIDEO_RE.match(segment) or segment.startswith(("photo", "album", "topic", "market")) \
            and re.search(r"-?\d+_\d+", segment):
        raise ValueError("Must be a vk.com profile or community link (https://vk.com/durov).")
    return segment


def _owner_ref(value, kind):
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    link = _split_link(value)
    if link is not None:
        host, path, query = link
        segment = _owner_from_path(path, query)
    else:
        segment = value.lstrip("@")
    if re.fullmatch(r"-?\d{1,12}", segment):
        number = int(segment)
        if number == 0:
            raise ValueError("Must be a positive numeric id.")
        if kind == "user" and number < 0:
            raise ValueError("A negative id is a community: use the `community` param of /vk/communities/*.")
        return {"id": abs(number), "screen_name": None}
    alias = _NUMERIC_ALIAS_RE.match(segment)
    if alias:
        prefix, number = alias.group(1).lower(), int(alias.group(2))
        if kind == "user" and prefix != "id":
            raise ValueError(f"'{segment}' is a community: use the `community` param of /vk/communities/*.")
        if kind == "community" and prefix == "id":
            raise ValueError(f"'{segment}' is a user profile: use the `user` param of /vk/users/*.")
        return {"id": number, "screen_name": None}
    if not SCREEN_NAME_RE.match(segment):
        raise ValueError("Must be a numeric id, a screen name (letters, digits, '_' and '.') "
                         "or a vk.com link.")
    return {"id": None, "screen_name": segment}


def resolve_user(value):
    """Numeric id / 'id<N>' / screen name / profile link -> owner ref."""
    return _owner_ref(value, "user")


def resolve_community(value):
    """Numeric id / 'club<N>' / screen name / community link -> owner ref
    (the id is the positive group id)."""
    return _owner_ref(value, "community")


def _object_from(value, pattern, label, example):
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    plain = _OBJECT_RE.match(value)
    if plain:
        return int(plain.group(1)), int(plain.group(2))
    link = _split_link(value)
    if link is not None:
        host, path, query = link
        haystack = path + " " + " ".join(v for values in query.values() for v in values)
        match = pattern.search(haystack)
        if match:
            return int(match.group(1)), int(match.group(2))
        if label == "video":
            oid, vid = query.get("oid", [None])[0], query.get("id", [None])[0]
            if oid and vid and re.fullmatch(r"-?\d+", oid) and vid.isdigit():
                return int(oid), int(vid)
        raise ValueError(f"Must be a vk.com {label} link ({example}).")
    match = pattern.fullmatch(value)
    if match:
        return int(match.group(1)), int(match.group(2))
    raise ValueError(f"Must be a {label} id like -22822305_1736006, or a vk.com {label} link ({example}).")


def resolve_post(value):
    owner_id, post_id = _object_from(value, _WALL_RE, "post", "https://vk.com/wall-22822305_1736006")
    return {"owner_id": owner_id, "post_id": post_id}


def resolve_video(value):
    owner_id, video_id = _object_from(value, _VIDEO_RE, "video",
                                      "https://vk.com/video-22822305_456243154 or https://vkvideo.ru/clip-1_2")
    return {"owner_id": owner_id, "video_id": video_id}


def resolve_article(value):
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    link = _split_link(value)
    if link is not None:
        host, path, query = link
        segment = path.strip("/").split("/")[0] if path.strip("/") else ""
        if not segment.startswith("@"):
            raise ValueError("Must be a vk.com article link (https://vk.com/@vk-verify).")
        value = segment
    match = _ARTICLE_RE.match(value)
    if not match:
        raise ValueError("Must be an article slug like @vk-verify, or a vk.com article link "
                         "(https://vk.com/@vk-verify).")
    return match.group(1)


# ---- links -------------------------------------------------------------------

def owner_link(owner_id, screen_name=None):
    """Profile / community link: the screen name when known, else VK's own
    numeric alias (vk.com/id1, vk.com/club22822305)."""
    if screen_name:
        return f"{SITE}/{screen_name}"
    if owner_id is None:
        return None
    owner_id = int(owner_id)
    return f"{SITE}/club{-owner_id}" if owner_id < 0 else f"{SITE}/id{owner_id}"


def post_link(owner_id, post_id):
    return f"{SITE}/wall{owner_id}_{post_id}" if owner_id is not None and post_id is not None else None


def comment_link(owner_id, post_id, comment_id):
    if None in (owner_id, post_id, comment_id):
        return None
    return f"{SITE}/wall{owner_id}_{post_id}?reply={comment_id}"


def video_link(owner_id, video_id, is_clip=False):
    if owner_id is None or video_id is None:
        return None
    return f"{SITE}/{'clip' if is_clip else 'video'}{owner_id}_{video_id}"


def photo_link(owner_id, photo_id):
    return f"{SITE}/photo{owner_id}_{photo_id}" if owner_id is not None and photo_id is not None else None


def article_link(slug):
    return f"{SITE}/@{slug}" if slug else None


# ---- choice tables --------------------------------------------------------------
# Upstream tokens for the public choice values (catalog.getSearchGroups /
# catalog.getVideoSearch search_filters, captured 2026-11-03).

COMMUNITY_SORT = {"relevant": "relevant", "popular": "popularity", "members": "members"}
COMMUNITY_TYPE = {"group": "group", "page": "page", "event": "event"}
VIDEO_SORT = {"relevant": 2, "latest": 0, "long": 1}
VIDEO_CONTENT_TYPE = {"all": "all", "videos": "video", "clips": "clip", "live": "live"}
VIDEO_DURATION = {"any": "any", "long": "long", "short": "short"}
POST_FILTER = {"all": "all", "owner": "owner", "others": "others"}
COMMENT_SORT = {"asc": "asc", "desc": "desc", "smart": "smart"}
VIDEO_COMMENT_SORT = {"asc": "asc", "desc": "desc"}
