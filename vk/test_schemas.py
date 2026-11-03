"""Offline tests for the /vk/* request schemas and reference resolvers.

    python -m pytest vk/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vk import refs, schemas  # noqa: E402


# ---- resolvers ---------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("durov", {"id": None, "screen_name": "durov"}),
    ("@durov", {"id": None, "screen_name": "durov"}),
    ("1", {"id": 1, "screen_name": None}),
    ("id1", {"id": 1, "screen_name": None}),
    ("ID1", {"id": 1, "screen_name": None}),
    ("https://vk.com/durov", {"id": None, "screen_name": "durov"}),
    ("https://vk.ru/durov?z=photo1_2", {"id": None, "screen_name": "durov"}),
    ("https://m.vk.com/id1", {"id": 1, "screen_name": None}),
    ("vk.com/durov", {"id": None, "screen_name": "durov"}),
    ("//vk.com/durov/", {"id": None, "screen_name": "durov"}),
])
def test_resolve_user(value, expected):
    assert refs.resolve_user(value) == expected


@pytest.mark.parametrize("value", [
    "", "   ", "-1", "0", "club1", "public22822305",
    "https://vk.com/wall-1_2", "https://vk.com/video-1_2", "https://vk.com/feed",
    "https://example.com/durov", "two words", "a" * 33, "https://vk.com/@vk-verify",
])
def test_resolve_user_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_user(value)


@pytest.mark.parametrize("value,expected", [
    ("vk", {"id": None, "screen_name": "vk"}),
    ("22822305", {"id": 22822305, "screen_name": None}),
    ("-22822305", {"id": 22822305, "screen_name": None}),
    ("club22822305", {"id": 22822305, "screen_name": None}),
    ("public1", {"id": 1, "screen_name": None}),
    ("event5", {"id": 5, "screen_name": None}),
    ("https://vk.com/vk", {"id": None, "screen_name": "vk"}),
    ("https://vk.com/club1", {"id": 1, "screen_name": None}),
])
def test_resolve_community(value, expected):
    assert refs.resolve_community(value) == expected


@pytest.mark.parametrize("value", ["", "id1", "https://vk.com/wall-1_2", "https://t.me/vk", "0"])
def test_resolve_community_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_community(value)


@pytest.mark.parametrize("value,expected", [
    ("-22822305_1736006", {"owner_id": -22822305, "post_id": 1736006}),
    ("wall-22822305_1736006", {"owner_id": -22822305, "post_id": 1736006}),
    ("1_2", {"owner_id": 1, "post_id": 2}),
    ("https://vk.com/wall-22822305_1736006", {"owner_id": -22822305, "post_id": 1736006}),
    ("https://vk.com/vk?w=wall-22822305_1736006", {"owner_id": -22822305, "post_id": 1736006}),
    ("https://vk.com/feed?z=wall1_2%2F1", {"owner_id": 1, "post_id": 2}),
    ("https://m.vk.ru/wall-22822305_1736006?reply=5", {"owner_id": -22822305, "post_id": 1736006}),
])
def test_resolve_post(value, expected):
    assert refs.resolve_post(value) == expected


@pytest.mark.parametrize("value", ["", "durov", "-22822305", "https://vk.com/video-1_2", "https://example.com/wall-1_2"])
def test_resolve_post_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_post(value)


@pytest.mark.parametrize("value,expected", [
    ("-22822305_456243154", {"owner_id": -22822305, "video_id": 456243154}),
    ("video-22822305_456243154", {"owner_id": -22822305, "video_id": 456243154}),
    ("clip-22822305_456243517", {"owner_id": -22822305, "video_id": 456243517}),
    ("https://vkvideo.ru/video-22822305_456243154", {"owner_id": -22822305, "video_id": 456243154}),
    ("https://vk.com/clip-22822305_456243517", {"owner_id": -22822305, "video_id": 456243517}),
    ("https://vk.com/video_ext.php?oid=-22822305&id=456243154&hash=x", {"owner_id": -22822305, "video_id": 456243154}),
    ("https://vk.com/vk?z=video-22822305_456243154%2Fpl_-22822305_-2", {"owner_id": -22822305, "video_id": 456243154}),
    ("https://vkvideo.ru/video1_456239023", {"owner_id": 1, "video_id": 456239023}),
])
def test_resolve_video(value, expected):
    assert refs.resolve_video(value) == expected


@pytest.mark.parametrize("value", ["", "x", "https://vk.com/wall-1_2", "https://youtube.com/watch?v=1"])
def test_resolve_video_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_video(value)


@pytest.mark.parametrize("value,expected", [
    ("@vk-verify", "vk-verify"),
    ("vk-verify", "vk-verify"),
    ("https://vk.com/@vk-verify", "vk-verify"),
    ("https://m.vk.com/@vk-verify?ref=x", "vk-verify"),
    ("https://vk.ru/@durov-my.article_1", "durov-my.article_1"),
])
def test_resolve_article(value, expected):
    assert refs.resolve_article(value) == expected


@pytest.mark.parametrize("value", ["", "vk", "https://vk.com/vk", "https://example.com/@vk-verify", "@"])
def test_resolve_article_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_article(value)


def test_links():
    assert refs.owner_link(1) == "https://vk.com/id1"
    assert refs.owner_link(-22822305) == "https://vk.com/club22822305"
    assert refs.owner_link(1, "durov") == "https://vk.com/durov"
    assert refs.post_link(-22822305, 1736006) == "https://vk.com/wall-22822305_1736006"
    assert refs.video_link(-1, 2) == "https://vk.com/video-1_2"
    assert refs.video_link(-1, 2, is_clip=True) == "https://vk.com/clip-1_2"
    assert refs.photo_link(1, 2) == "https://vk.com/photo1_2"
    assert refs.article_link("vk-verify") == "https://vk.com/@vk-verify"
    assert refs.comment_link(-1, 2, 3) == "https://vk.com/wall-1_2?reply=3"
    assert refs.post_link(None, 1) is None


# ---- schemas -----------------------------------------------------------------------------------

def test_user_schema():
    assert schemas.UserSchema().load({"user": " https://vk.com/durov "}) == {"user": {"id": None, "screen_name": "durov"}}
    with pytest.raises(ValidationError) as e:
        schemas.UserSchema().load({"user": "club1"})
    assert "community" in str(e.value)
    with pytest.raises(ValidationError):
        schemas.UserSchema().load({})
    with pytest.raises(ValidationError):   # sibling params are rejected
        schemas.UserSchema().load({"user": "durov", "url": "https://vk.com/durov"})


def test_user_posts_schema():
    loaded = schemas.UserPostsSchema().load({"user": "1", "page": "3", "filter": "Owner"})
    assert loaded == {"user": {"id": 1, "screen_name": None}, "page": 3, "filter": "owner"}
    assert schemas.UserPostsSchema().load({"user": "1"})["filter"] == "all"
    with pytest.raises(ValidationError):
        schemas.UserPostsSchema().load({"user": "1", "filter": "mine"})
    with pytest.raises(ValidationError):
        schemas.UserPostsSchema().load({"user": "1", "page": "0"})
    with pytest.raises(ValidationError):
        schemas.UserPostsSchema().load({"user": "1", "page": str(schemas.MAX_PAGE + 1)})


def test_posts_search_schema():
    loaded = schemas.CommunityPostsSearchSchema().load({"community": "vk", "query": " VK ", "owners_only": "no"})
    assert loaded == {"community": {"id": None, "screen_name": "vk"}, "query": "VK", "page": 1, "owners_only": False}
    # owners_only defaults to true: VK answers that in ~2 s, the full search takes up to a minute
    assert schemas.UserPostsSearchSchema().load({"user": "1", "query": "x"})["owners_only"] is True
    assert schemas.CommunityPostsSearchSchema().load({"community": "vk", "query": "x"})["owners_only"] is True
    with pytest.raises(ValidationError):
        schemas.CommunityPostsSearchSchema().load({"community": "vk"})


def test_photos_schema():
    assert schemas.UserPhotosSchema().load({"user": "1"})["album"] == "all"
    assert schemas.UserPhotosSchema().load({"user": "1", "album": "Wall"})["album"] == "wall"
    assert schemas.CommunityPhotosSchema().load({"community": "vk", "album": "136592355"})["album"] == "136592355"
    with pytest.raises(ValidationError):
        schemas.UserPhotosSchema().load({"user": "1", "album": "friends"})


def test_clips_schema_caps_the_walk():
    assert schemas.UserClipsSchema().load({"user": "1", "page": "50"})["page"] == 50
    with pytest.raises(ValidationError):
        schemas.UserClipsSchema().load({"user": "1", "page": "51"})


def test_communities_search_schema():
    loaded = schemas.CommunitiesSearchSchema().load({"query": "python", "sort": "Popular", "type": "page"})
    assert loaded == {"query": "python", "page": 1, "sort": "popularity", "type": "page"}
    assert schemas.CommunitiesSearchSchema().load({"query": "python"})["sort"] is None
    with pytest.raises(ValidationError):
        schemas.CommunitiesSearchSchema().load({"query": "python", "sort": "newest"})
    with pytest.raises(ValidationError):
        schemas.CommunitiesSearchSchema().load({"query": ""})


def test_community_schema():
    assert schemas.CommunitySchema().load({"community": "https://vk.com/club22822305"}) == \
        {"community": {"id": 22822305, "screen_name": None}}
    with pytest.raises(ValidationError) as e:
        schemas.CommunitySchema().load({"community": "id1"})
    assert "user" in str(e.value)


def test_post_schemas():
    assert schemas.PostSchema().load({"post": "https://vk.com/wall-22822305_1736006"}) == \
        {"post": {"owner_id": -22822305, "post_id": 1736006}}
    loaded = schemas.PostCommentsSchema().load({"post": "-1_2", "sort": "DESC", "comment": "7", "page": "2"})
    assert loaded == {"post": {"owner_id": -1, "post_id": 2}, "page": 2, "sort": "desc", "comment": 7}
    assert schemas.PostCommentsSchema().load({"post": "-1_2"})["sort"] == "asc"
    with pytest.raises(ValidationError):
        schemas.PostCommentsSchema().load({"post": "-1_2", "comment": "0"})
    with pytest.raises(ValidationError):
        schemas.PostSchema().load({"post": "durov"})


def test_video_schemas():
    loaded = schemas.VideosSearchSchema().load({"query": "python", "sort": "latest", "content_type": "Clips",
                                                "duration": "short", "hd": "true"})
    assert loaded == {"query": "python", "page": 1, "sort": 0, "content_type": "clip", "duration": "short", "hd": True}
    assert schemas.VideosSearchSchema().load({"query": "x"})["hd"] is False
    with pytest.raises(ValidationError):
        schemas.VideosSearchSchema().load({"query": "x", "content_type": "movies"})
    assert schemas.VideoSchema().load({"video": "https://vkvideo.ru/clip-1_2"}) == {"video": {"owner_id": -1, "video_id": 2}}
    loaded = schemas.VideoCommentsSchema().load({"video": "-1_2"})
    assert loaded == {"video": {"owner_id": -1, "video_id": 2}, "page": 1, "sort": "desc"}
    with pytest.raises(ValidationError):
        schemas.VideoCommentsSchema().load({"video": "-1_2", "sort": "smart"})


def test_article_schema():
    assert schemas.ArticleSchema().load({"article": "https://vk.com/@vk-verify"}) == {"article": "vk-verify"}
    with pytest.raises(ValidationError) as e:
        schemas.ArticleSchema().load({"article": "https://vk.com/vk"})
    assert "article" in str(e.value)


def test_unknown_params_are_rejected():
    with pytest.raises(ValidationError):
        schemas.VideosSearchSchema().load({"query": "x", "q": "y"})
