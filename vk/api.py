"""The /vk/* endpoint functions (route_glue's route_table calls them with
the schema's loaded kwargs). Every endpoint caches its own result through
cache.cached_call keyed on the validated params (vk/cache_config.py), so
the routes register without a route-level cache.

Owner inputs arrive as {"id", "screen_name"} refs (vk/refs.py); a screen
name is resolved once through utils.resolveScreenName (cached a day) and
checked against the collection (a community passed as `user` is a 400
that says so). Walls, videos, photos and articles of users and communities
share one implementation per collection, keyed on the signed owner id, so
/vk/users/posts?user=id1 and /vk/communities/posts?community=club1 never
fetch the same wall twice.

Pagination: offset-based lists (walls, followers, videos, photos, articles,
comments) are plain pages with VK's own totals. Cursor-based lists (clips,
the community and video searches — VK hands out an opaque next_from) are
walked page by page through _cursor_page: page N needs page N-1's cursor,
every page is cached, so a sequential reader pays one call per page and a
cold jump to page N pays N calls once.
"""
import math

from cache import cached_call
from vk import cache_config as ttl
from vk import parsers, refs
from vk.fetch import (VkBadRequest, VkNotFound, fetch_article_page, fetch_articles, fetch_catalog_section,
                      fetch_clips, fetch_community, fetch_community_addresses, fetch_community_search,
                      fetch_followers, fetch_members_preview, fetch_photos, fetch_post, fetch_post_comments,
                      fetch_resolve_screen_name, fetch_user, fetch_video, fetch_video_comments,
                      fetch_video_search, fetch_videos, fetch_wall, fetch_wall_search)

POSTS_PER_PAGE = 20        # VK's own wall page
FOLLOWERS_PER_PAGE = 50
VIDEOS_PER_PAGE = 20
CLIPS_PER_PAGE = 20
PHOTOS_PER_PAGE = 50
ARTICLES_PER_PAGE = 20
COMMENTS_PER_PAGE = 50
SEARCH_PER_PAGE = 20
MEMBERS_PREVIEW = 8        # the most an anonymous token may read (VK error 100 beyond)


# ---- shared plumbing ------------------------------------------------------------

def _pagination(page, per_page, total=None, has_next=None):
    """The block route_glue.paginate lifts into count / per_page / next /
    previous. With a known total the page count is derived; a cursor list
    passes has_next and may still carry the total VK reports."""
    block = {"page": page, "items_per_page": per_page,
             "total_pages": math.ceil(total / per_page) if total else (0 if total == 0 else None),
             "total_count": total}
    if has_next is not None:
        block["has_next"] = bool(has_next)
    return block


def _resolve_screen_name(screen_name):
    def impl(**data):
        found = fetch_resolve_screen_name(data["screen_name"])
        return found if isinstance(found, dict) and found.get("object_id") else {}
    return cached_call("vk.resolve", {"screen_name": screen_name}, impl, ttl.RESOLVE_CACHE)


def _owner_id(ref, kind):
    """{"id", "screen_name"} -> the signed owner id (users positive,
    communities negative), resolving screen names against VK."""
    if ref.get("id"):
        return ref["id"] if kind == "user" else -ref["id"]
    name = ref.get("screen_name")
    found = _resolve_screen_name(name)
    object_type, object_id = found.get("type"), found.get("object_id")
    if not object_id:
        raise VkNotFound(f"'{name}' is not a VK user or community", reason="unknown")
    if kind == "user":
        if object_type != "user":
            raise ValueError(f"'{name}' is a VK community, not a user: use the `community` param of /vk/communities/*.")
        return object_id
    if object_type == "user":
        raise ValueError(f"'{name}' is a VK user, not a community: use the `user` param of /vk/users/*.")
    return -object_id


def _owner_block(owner_id):
    return {"id": owner_id, "type": "community" if owner_id < 0 else "user", "link": refs.owner_link(owner_id)}


def _cursor_page(namespace, params, page, fetch_page, cache_ttl):
    """Page `page` of a cursor-paged list. fetch_page(start_from) ->
    {"items": [...], "next_from": str | None, ...extras}; each page record
    is cached under namespace + params + page, and page N reads page N-1's
    cursor from its (cached) record."""
    def record(number):
        def impl(**data):
            start_from = None
            if number > 1:
                previous = record(number - 1)
                if not previous.get("next_from"):
                    return {"items": [], "next_from": None, "past_end": True,
                            **{k: v for k, v in previous.items() if k not in ("items", "next_from", "past_end")}}
                start_from = previous["next_from"]
            out = fetch_page(start_from, previous_record=previous if number > 1 else None)
            out.setdefault("next_from", None)
            return out
        return cached_call(namespace, {**params, "page": number}, impl, cache_ttl)
    return record(page)


# ---- users -----------------------------------------------------------------------

def _user_details(user):
    user_id = _owner_id(user, "user")
    found = fetch_user(user_id)
    if not isinstance(found, list) or not found:
        raise VkNotFound(f"user {user_id} not found", reason="unknown", user=user_id)
    record = parsers.parse_user(found[0])
    if record.get("deactivated"):
        raise VkNotFound(f"user {user_id} is {record['deactivated']}", reason=record["deactivated"], user=user_id)
    record.pop("deactivated", None)
    return record


def users_details(**data):
    return cached_call("vk.users_details", data, _user_details, ttl.USER_CACHE)


def _followers(user, page):
    user_id = _owner_id(user, "user")
    cards, total = parsers.parse_cards(fetch_followers(user_id, (page - 1) * FOLLOWERS_PER_PAGE, FOLLOWERS_PER_PAGE))
    for card in cards:
        card.pop("type", None)
    return {"user": _owner_block(user_id), "results": cards,
            "pagination": _pagination(page, FOLLOWERS_PER_PAGE, total)}


def users_followers(**data):
    return cached_call("vk.users_followers", data, _followers, ttl.FOLLOWERS_CACHE)


# ---- communities -------------------------------------------------------------------

def _community_details(community):
    group_id = -_owner_id(community, "community")
    found = fetch_community(group_id)
    groups = found.get("groups") if isinstance(found, dict) else found
    if not isinstance(groups, list) or not groups:
        raise VkNotFound(f"community {group_id} not found", reason="unknown", community=group_id)
    raw = groups[0]
    addresses = []
    if isinstance(raw, dict) and (raw.get("addresses") or {}).get("is_enabled"):
        try:
            addresses = (fetch_community_addresses(group_id) or {}).get("items") or []
        except (VkNotFound, VkBadRequest):
            addresses = []
    record = parsers.parse_community(raw, addresses)
    if record.pop("is_stub", False):
        raise VkNotFound(f"community {group_id} not found", reason="unknown", community=group_id)
    if record.get("deactivated"):
        raise VkNotFound(f"community {group_id} is {record['deactivated']}", reason=record["deactivated"],
                         community=group_id)
    record.pop("deactivated", None)
    return record


def communities_details(**data):
    return cached_call("vk.communities_details", data, _community_details, ttl.COMMUNITY_CACHE)


def _members(community):
    group_id = -_owner_id(community, "community")
    cards, total = parsers.parse_cards(fetch_members_preview(group_id, MEMBERS_PREVIEW))
    for card in cards:
        card.pop("type", None)
    return {"community": _owner_block(-group_id), "members_count": total,
            "preview_limit": MEMBERS_PREVIEW, "results": cards}


def communities_members(**data):
    return cached_call("vk.communities_members", data, _members, ttl.MEMBERS_CACHE)


def _dedupe(items, previous_record, next_from):
    """Catalog pages past the first repeat items already served (VK's video
    search re-serves half of page 2 on pages 3+, 2026-11-03): drop what
    earlier pages carried, and end the walk after two pages in a row that
    bring nothing new (one empty page can be VK reshuffling, two is the end
    of what it will serve anonymously). The cumulative id list and the empty
    streak ride in each page's cached record."""
    seen = list((previous_record or {}).get("seen") or [])
    seen_set = set(seen)
    fresh = []
    for item in items:
        key = f"{item.get('owner_id')}_{item.get('id')}"
        if key in seen_set:
            continue
        seen_set.add(key)
        seen.append(key)
        fresh.append(item)
    streak = 0 if fresh else int((previous_record or {}).get("empty_streak") or 0) + 1
    if not items or streak >= 2:
        next_from = None
    return fresh, seen, next_from, streak


def _community_search_page(start_from, previous_record=None, *, query, sort, community_type):
    if start_from is None:
        response = fetch_community_search(query, SEARCH_PER_PAGE, sort, community_type)
    else:
        response = fetch_catalog_section(previous_record["section_id"], start_from, SEARCH_PER_PAGE)
    cards, section_id, next_from = parsers.parse_community_search(response)
    for card in cards:
        card.pop("type", None)
        card.pop("deactivated", None)
    cards, seen, next_from, streak = _dedupe(cards, previous_record, next_from)
    return {"items": cards, "next_from": next_from, "seen": seen, "empty_streak": streak,
            "section_id": section_id or (previous_record or {}).get("section_id")}


def _communities_search(query, page, sort, type):
    def fetch_page(start_from, previous_record=None):
        return _community_search_page(start_from, previous_record, query=query, sort=sort, community_type=type)
    record = _cursor_page("vk.communities_search_page", {"query": query, "sort": sort, "type": type}, page,
                          fetch_page, ttl.SEARCH_CACHE)
    public_sort = next((k for k, v in refs.COMMUNITY_SORT.items() if v == sort), None) if sort else "relevant"
    return {"query": query, "sort": public_sort, "type": type, "results": record["items"],
            "pagination": _pagination(page, SEARCH_PER_PAGE, has_next=bool(record.get("next_from")))}


def communities_search(**data):
    # the per-page records are cached inside _cursor_page; this wrapper is
    # the public shape and needs no second cache row
    return _communities_search(**data)


# ---- walls (users + communities) -----------------------------------------------------

def _wall_page(owner_id, page, post_filter):
    def impl(**data):
        posts, total = parsers.parse_wall(fetch_wall(owner_id, (page - 1) * POSTS_PER_PAGE, POSTS_PER_PAGE,
                                                     post_filter))
        return {"posts": posts, "total": total}
    return cached_call("vk.wall", {"owner_id": owner_id, "page": page, "filter": post_filter}, impl, ttl.POSTS_CACHE)


def _posts(ref, kind, page, post_filter):
    owner_id = _owner_id(ref, kind)
    record = _wall_page(owner_id, page, post_filter)
    return {"owner": _owner_block(owner_id), "filter": post_filter, "results": record["posts"],
            "pagination": _pagination(page, POSTS_PER_PAGE, record["total"])}


def users_posts(user, page=1, filter="all"):
    return _posts(user, "user", page, filter)


def communities_posts(community, page=1, filter="all"):
    return _posts(community, "community", page, filter)


def _wall_search_page(owner_id, query, page, owners_only):
    def impl(**data):
        posts, page_size = parsers.parse_wall_search(fetch_wall_search(
            owner_id, query, (page - 1) * POSTS_PER_PAGE, POSTS_PER_PAGE, owners_only))
        # wall.search's `count` is the size of the page it returned, not a
        # total (2026-11-03), so the next link follows a full page
        return {"posts": posts, "has_next": page_size >= POSTS_PER_PAGE}
    return cached_call("vk.wall_search", {"owner_id": owner_id, "query": query, "page": page,
                                          "owners_only": bool(owners_only)}, impl, ttl.POSTS_CACHE)


def _posts_search(ref, kind, query, page, owners_only):
    owner_id = _owner_id(ref, kind)
    record = _wall_search_page(owner_id, query, page, owners_only)
    return {"owner": _owner_block(owner_id), "query": query, "owners_only": bool(owners_only),
            "results": record["posts"],
            "pagination": _pagination(page, POSTS_PER_PAGE, has_next=record["has_next"])}


def users_posts_search(user, query, page=1, owners_only=True):
    return _posts_search(user, "user", query, page, owners_only)


def communities_posts_search(community, query, page=1, owners_only=True):
    return _posts_search(community, "community", query, page, owners_only)


# ---- videos / clips / photos / articles of an owner ------------------------------------

def _videos_page(owner_id, page):
    def impl(**data):
        videos, total = parsers.parse_videos(fetch_videos(owner_id, (page - 1) * VIDEOS_PER_PAGE, VIDEOS_PER_PAGE))
        return {"videos": videos, "total": total}
    return cached_call("vk.videos", {"owner_id": owner_id, "page": page}, impl, ttl.VIDEOS_CACHE)


def _videos(ref, kind, page):
    owner_id = _owner_id(ref, kind)
    record = _videos_page(owner_id, page)
    return {"owner": _owner_block(owner_id), "results": record["videos"],
            "pagination": _pagination(page, VIDEOS_PER_PAGE, record["total"])}


def users_videos(user, page=1):
    return _videos(user, "user", page)


def communities_videos(community, page=1):
    return _videos(community, "community", page)


def _clips(ref, kind, page):
    owner_id = _owner_id(ref, kind)

    def fetch_page(start_from, previous_record=None):
        clips, total, next_from = parsers.parse_clips(fetch_clips(owner_id, CLIPS_PER_PAGE, start_from))
        return {"items": clips, "next_from": next_from, "total": total}
    record = _cursor_page("vk.clips_page", {"owner_id": owner_id}, page, fetch_page, ttl.CLIPS_CACHE)
    return {"owner": _owner_block(owner_id), "results": record["items"],
            "pagination": _pagination(page, CLIPS_PER_PAGE, record.get("total"),
                                      has_next=bool(record.get("next_from")))}


def users_clips(user, page=1):
    return _clips(user, "user", page)


def communities_clips(community, page=1):
    return _clips(community, "community", page)


def _photos_page(owner_id, album, page):
    def impl(**data):
        photos, total = parsers.parse_photos(fetch_photos(owner_id, album, (page - 1) * PHOTOS_PER_PAGE,
                                                          PHOTOS_PER_PAGE))
        return {"photos": photos, "total": total}
    return cached_call("vk.photos", {"owner_id": owner_id, "album": album, "page": page}, impl, ttl.PHOTOS_CACHE)


def _photos(ref, kind, page, album):
    owner_id = _owner_id(ref, kind)
    record = _photos_page(owner_id, album, page)
    return {"owner": _owner_block(owner_id), "album": album, "results": record["photos"],
            "pagination": _pagination(page, PHOTOS_PER_PAGE, record["total"])}


def users_photos(user, page=1, album="all"):
    return _photos(user, "user", page, album)


def communities_photos(community, page=1, album="all"):
    return _photos(community, "community", page, album)


def _articles(community, page):
    owner_id = _owner_id(community, "community")

    def impl(**data):
        articles, total = parsers.parse_articles(fetch_articles(owner_id, (page - 1) * ARTICLES_PER_PAGE,
                                                                ARTICLES_PER_PAGE))
        return {"articles": articles, "total": total}
    record = cached_call("vk.articles", {"owner_id": owner_id, "page": page}, impl, ttl.ARTICLES_CACHE)
    return {"owner": _owner_block(owner_id), "results": record["articles"],
            "pagination": _pagination(page, ARTICLES_PER_PAGE, record["total"])}


def communities_articles(community, page=1):
    return _articles(community, page)


# ---- posts ---------------------------------------------------------------------------

def _post_details(post):
    owner_id, post_id = post["owner_id"], post["post_id"]
    record = parsers.parse_post_by_id(fetch_post(owner_id, post_id))
    if record is None:
        raise VkNotFound(f"post {owner_id}_{post_id} not found", reason="unknown", post=f"{owner_id}_{post_id}")
    if record.get("is_deleted"):
        raise VkNotFound(f"post {owner_id}_{post_id} was deleted", reason="deleted", post=f"{owner_id}_{post_id}")
    return record


def posts_details(**data):
    return cached_call("vk.posts_details", data, _post_details, ttl.POST_CACHE)


def _post_comments(post, page, sort, comment):
    owner_id, post_id = post["owner_id"], post["post_id"]
    response = fetch_post_comments(owner_id, post_id, (page - 1) * COMMENTS_PER_PAGE, COMMENTS_PER_PAGE,
                                   sort, comment)
    comments, top_level, total = parsers.parse_comments(response, owner_id, post_id)
    out = {"post": {"id": post_id, "owner_id": owner_id, "link": refs.post_link(owner_id, post_id)},
           "sort": sort, "comments_count": total}
    if comment:
        out["replies_to"] = comment
    out["results"] = comments
    out["pagination"] = _pagination(page, COMMENTS_PER_PAGE, top_level if top_level is not None else total)
    return out


def posts_comments(**data):
    return cached_call("vk.posts_comments", data, _post_comments, ttl.COMMENTS_CACHE)


# ---- videos ----------------------------------------------------------------------------

def _video_details(video):
    owner_id, video_id = video["owner_id"], video["video_id"]
    record = parsers.parse_video_by_id(fetch_video(owner_id, video_id))
    if record is None:
        raise VkNotFound(f"video {owner_id}_{video_id} not found", reason="unknown", video=f"{owner_id}_{video_id}")
    return record


def videos_details(**data):
    return cached_call("vk.videos_details", data, _video_details, ttl.VIDEO_CACHE)


def _video_comments(video, page, sort):
    owner_id, video_id = video["owner_id"], video["video_id"]
    response = fetch_video_comments(owner_id, video_id, (page - 1) * COMMENTS_PER_PAGE, COMMENTS_PER_PAGE, sort)
    comments, top_level, total = parsers.parse_comments(response, owner_id, video_id)
    for item in comments:
        item["video_id"] = item.pop("post_id", None)
        item["link"] = refs.video_link(owner_id, video_id)
        for reply in ((item.get("replies") or {}).get("items") or []):
            reply["video_id"] = reply.pop("post_id", None)
            reply["link"] = refs.video_link(owner_id, video_id)
    return {"video": {"id": video_id, "owner_id": owner_id, "link": refs.video_link(owner_id, video_id)},
            "sort": sort, "comments_count": total, "results": comments,
            "pagination": _pagination(page, COMMENTS_PER_PAGE, top_level if top_level is not None else total)}


def videos_comments(**data):
    return cached_call("vk.videos_comments", data, _video_comments, ttl.COMMENTS_CACHE)


def _video_search_page(start_from, previous_record=None, *, query, sort, content_type, duration, hd):
    if start_from is None:
        response = fetch_video_search(query, SEARCH_PER_PAGE, sort, content_type, duration, hd)
    else:
        response = fetch_catalog_section(previous_record["section_id"], start_from, SEARCH_PER_PAGE)
    videos, playlists, section_id, next_from = parsers.parse_video_search(response)
    videos, seen, next_from, streak = _dedupe(videos, previous_record, next_from)
    return {"items": videos, "playlists": playlists, "next_from": next_from, "seen": seen,
            "empty_streak": streak, "section_id": section_id or (previous_record or {}).get("section_id")}


def _videos_search(query, page, sort, content_type, duration, hd):
    params = {"query": query, "sort": sort, "content_type": content_type, "duration": duration, "hd": bool(hd)}

    def fetch_page(start_from, previous_record=None):
        return _video_search_page(start_from, previous_record, query=query, sort=sort, content_type=content_type,
                                  duration=duration, hd=hd)
    record = _cursor_page("vk.videos_search_page", params, page, fetch_page, ttl.SEARCH_CACHE)
    public_sort = next((k for k, v in refs.VIDEO_SORT.items() if v == sort), None) if sort is not None else "relevant"
    # VK's video catalog lays page 1 out as "new videos by creator" + "all
    # videos" (about 30 records) and serves 10 per page after that, so the
    # page size is what the page holds
    return {"query": query, "sort": public_sort, "content_type": content_type or "all",
            "duration": duration or "any", "hd": bool(hd),
            "results": record["items"], "playlists": record.get("playlists") or [],
            "pagination": _pagination(page, len(record["items"]) or SEARCH_PER_PAGE,
                                      has_next=bool(record.get("next_from")))}


def videos_search(**data):
    return _videos_search(**data)


# ---- articles -----------------------------------------------------------------------------

def _article_details(article):
    return parsers.parse_article_page(fetch_article_page(article), article)


def articles_details(**data):
    return cached_call("vk.articles_details", data, _article_details, ttl.ARTICLE_CACHE)
