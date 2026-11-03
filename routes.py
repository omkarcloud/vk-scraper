"""The 22 VK endpoints. Every path is served with and without the `/vk`
prefix, so code generated against the hosted API on RapidAPI (paths like
/users/details) runs unchanged against this server.

Params are validated by the marshmallow schemas in vk/schemas.py (ONE param
per input: `user` / `community` take a numeric ID, id<N> / club<N>, a screen
name or a vk.com link; `post`, `video` and `article` take the
<owner>_<id> form or a vk.com / vkvideo.ru link); unknown params are
rejected."""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from schema_fields import load_query
from scraper_errors import BadRequest, NotFound
from vk import api, schemas


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The request query as unicode strings (bottle 0.12's .get() hands back
    latin-1 decoded bytes, so getunicode is mandatory)."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page_link(path, params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "", False)}
    query["page"] = page
    scheme, host = request.urlparts.scheme, request.urlparts.netloc
    return f"{scheme}://{host}{path}?{urlencode(query, doseq=True)}"


def paginate(result, path, params):
    """Lift the `pagination` block into the flat shape the hosted API
    returns: count / per_page / current_page / total_pages / next / previous.
    Lists VK publishes no total for (the searches, clips) carry `has_next`
    instead: the next link follows it and the totals stay null."""
    pagination = result.pop("pagination", None) or {}
    result.pop("count", None)
    page = _as_int(pagination.get("page")) or _as_int(params.get("page")) or 1
    if "has_next" in pagination:
        has_next = bool(pagination["has_next"])
        total_pages = pagination.get("total_pages")
        if total_pages is not None:
            total_pages = _as_int(total_pages, None)
    else:
        total_pages = max(_as_int(pagination.get("total_pages")), 0)
        has_next = page < total_pages
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(path, params, page + 1 if has_next else None),
        "previous": _page_link(path, params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def _error_body(message, exc):
    """{"error": message} plus the reason VK gave (deleted / private /
    unknown …) and the object it names."""
    body = {"error": message}
    reason = getattr(exc, "reason", None)
    if reason:
        body["reason"] = reason
        for key, value in (getattr(exc, "details", None) or {}).items():
            body.setdefault(key, value)
    return body


def call(label, schema_cls, impl, paginated=False):
    """Validate, run, map errors: bad params -> 400, missing entity -> 404,
    transport / blocks -> 500."""
    raw = query_dict()
    data, error = load_query(schema_cls, raw)
    if error:
        return json_response(error, 400)
    try:
        result = impl(**data)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response(_error_body(f"vk rejected the request: {e}", e), 400)
    except NotFound as e:
        return json_response(_error_body(str(e) or "not found", e), 404)
    except Exception as e:                 # retries exhausted / blocked
        return json_response({"error": f"vk {label} failed: {e}"}, 500)
    if paginated:
        result = paginate(result, request.path, raw)
    return json_response(result)


ENDPOINTS = [
    ("/users/details", schemas.UserSchema, api.users_details, False),
    ("/users/posts", schemas.UserPostsSchema, api.users_posts, True),
    ("/users/posts/search", schemas.UserPostsSearchSchema, api.users_posts_search, True),
    ("/users/followers", schemas.UserPagedSchema, api.users_followers, True),
    ("/users/videos", schemas.UserPagedSchema, api.users_videos, True),
    ("/users/clips", schemas.UserClipsSchema, api.users_clips, True),
    ("/users/photos", schemas.UserPhotosSchema, api.users_photos, True),
    ("/communities/search", schemas.CommunitiesSearchSchema, api.communities_search, True),
    ("/communities/details", schemas.CommunitySchema, api.communities_details, False),
    ("/communities/posts", schemas.CommunityPostsSchema, api.communities_posts, True),
    ("/communities/posts/search", schemas.CommunityPostsSearchSchema, api.communities_posts_search, True),
    ("/communities/videos", schemas.CommunityPagedSchema, api.communities_videos, True),
    ("/communities/clips", schemas.CommunityClipsSchema, api.communities_clips, True),
    ("/communities/photos", schemas.CommunityPhotosSchema, api.communities_photos, True),
    ("/communities/articles", schemas.CommunityPagedSchema, api.communities_articles, True),
    ("/communities/members", schemas.CommunitySchema, api.communities_members, False),
    ("/posts/details", schemas.PostSchema, api.posts_details, False),
    ("/posts/comments", schemas.PostCommentsSchema, api.posts_comments, True),
    ("/videos/search", schemas.VideosSearchSchema, api.videos_search, True),
    ("/videos/details", schemas.VideoSchema, api.videos_details, False),
    ("/videos/comments", schemas.VideoCommentsSchema, api.videos_comments, True),
    ("/articles/details", schemas.ArticleSchema, api.articles_details, False),
]


def mount(path, schema_cls, impl, paginated):
    """Serve a handler at /path and /vk/path."""
    label = path.strip("/")

    def handler():
        return call(label, schema_cls, impl, paginated)

    handler.__name__ = "vk_" + label.replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/vk" + path, method="GET")(handler)


for _path, _schema, _impl, _paginated in ENDPOINTS:
    mount(_path, _schema, _impl, _paginated)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, *_ in ENDPOINTS]})
