"""Marshmallow request schemas for every /vk/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair); the resolvers live in vk/refs.py:

    user       numeric id, "id<N>", a screen name, or a vk.com profile link
    community  numeric id, "club<N>", a screen name, or a vk.com community link
    post       "<owner>_<post>", "wall<owner>_<post>" or a vk.com post link
    video      "<owner>_<video>", "video…" / "clip…" or a vk.com / vkvideo.ru link
    article    "@owner-slug" or a vk.com article link

Pages are 1-based; the per-page sizes are the API's own (vk/api.py).
"""
from marshmallow import validate

from schema_fields import (BaseSchema, ChoiceField, Flag, PageField, PositiveInt, QueryField,
                           RefField, StrippedString)
from vk import refs

# VK walls run to tens of thousands of posts; 20 per page.
MAX_PAGE = 5000
# Catalog searches are cursor-walked (api._cursor_page): a deep page costs
# one upstream call per page walked once, so keep the depth modest.
MAX_SEARCH_PAGE = 50


class UserRefField(RefField):
    resolver = staticmethod(refs.resolve_user)


class CommunityRefField(RefField):
    resolver = staticmethod(refs.resolve_community)


class PostRefField(RefField):
    resolver = staticmethod(refs.resolve_post)


class VideoRefField(RefField):
    resolver = staticmethod(refs.resolve_video)


class ArticleRefField(RefField):
    resolver = staticmethod(refs.resolve_article)


class AlbumField(StrippedString):
    """all | wall | profile | saved | a numeric album id."""

    def __init__(self, **kwargs):
        kwargs.setdefault("load_default", "all")
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return "all"
        low = value.lower()
        if low in ("all", "wall", "profile", "saved"):
            return low
        if low.isdigit():
            return low
        from marshmallow import ValidationError
        raise ValidationError("Must be all, wall, profile, saved or a numeric album id.")


_USER = {"description": "VK user: numeric id, id<N>, screen name (durov) or a vk.com profile link"}
_COMMUNITY = {"description": "VK community: numeric id, club<N>, screen name (vk) or a vk.com community link"}
_PAGE = {"description": "1-based page"}


class UserSchema(BaseSchema):
    user = UserRefField(metadata=_USER)


class UserPostsSchema(BaseSchema):
    user = UserRefField(metadata=_USER)
    page = PageField(max_page=MAX_PAGE, metadata=_PAGE)
    filter = ChoiceField(refs.POST_FILTER, load_default="all", metadata={
        "description": "all (default), owner (the user's own posts) or others (posts by visitors)"})


class UserPostsSearchSchema(BaseSchema):
    user = UserRefField(metadata=_USER)
    query = QueryField(metadata={"description": "text to search for in the user's wall posts"})
    page = PageField(max_page=MAX_PAGE, metadata=_PAGE)
    owners_only = Flag(load_default=True, metadata={
        "description": "true (default) = only posts written by the user; false also searches visitors' posts (much slower)"})


class UserPagedSchema(BaseSchema):
    user = UserRefField(metadata=_USER)
    page = PageField(max_page=MAX_PAGE, metadata=_PAGE)


class UserClipsSchema(BaseSchema):
    user = UserRefField(metadata=_USER)
    page = PageField(max_page=MAX_SEARCH_PAGE, metadata=_PAGE)


class UserPhotosSchema(BaseSchema):
    user = UserRefField(metadata=_USER)
    page = PageField(max_page=MAX_PAGE, metadata=_PAGE)
    album = AlbumField(metadata={
        "description": "all (default, every public photo), wall, profile, saved or a numeric album id"})


class CommunitiesSearchSchema(BaseSchema):
    query = QueryField(metadata={"description": "community name or topic to search for"})
    page = PageField(max_page=MAX_SEARCH_PAGE, metadata=_PAGE)
    sort = ChoiceField(refs.COMMUNITY_SORT, metadata={
        "description": "relevant (default), popular or members (most members first)"})
    type = ChoiceField(refs.COMMUNITY_TYPE, metadata={
        "description": "restrict to group, page (public page) or event"})


class CommunitySchema(BaseSchema):
    community = CommunityRefField(metadata=_COMMUNITY)


class CommunityPostsSchema(BaseSchema):
    community = CommunityRefField(metadata=_COMMUNITY)
    page = PageField(max_page=MAX_PAGE, metadata=_PAGE)
    filter = ChoiceField(refs.POST_FILTER, load_default="all", metadata={
        "description": "all (default), owner (the community's own posts) or others (posts by members)"})


class CommunityPostsSearchSchema(BaseSchema):
    community = CommunityRefField(metadata=_COMMUNITY)
    query = QueryField(metadata={"description": "text to search for in the community's wall posts"})
    page = PageField(max_page=MAX_PAGE, metadata=_PAGE)
    owners_only = Flag(load_default=True, metadata={
        "description": "true (default) = only posts written by the community; false also searches members' posts (much slower)"})


class CommunityPagedSchema(BaseSchema):
    community = CommunityRefField(metadata=_COMMUNITY)
    page = PageField(max_page=MAX_PAGE, metadata=_PAGE)


class CommunityClipsSchema(BaseSchema):
    community = CommunityRefField(metadata=_COMMUNITY)
    page = PageField(max_page=MAX_SEARCH_PAGE, metadata=_PAGE)


class CommunityPhotosSchema(BaseSchema):
    community = CommunityRefField(metadata=_COMMUNITY)
    page = PageField(max_page=MAX_PAGE, metadata=_PAGE)
    album = AlbumField(metadata={
        "description": "all (default, every public photo), wall, profile, saved or a numeric album id"})


class PostSchema(BaseSchema):
    post = PostRefField(metadata={
        "description": "post id as <owner>_<post> (-22822305_1736006), wall-22822305_1736006, or a vk.com post link"})


class PostCommentsSchema(BaseSchema):
    post = PostRefField(metadata={
        "description": "post id as <owner>_<post> (-22822305_1736006), wall-22822305_1736006, or a vk.com post link"})
    page = PageField(max_page=MAX_PAGE, metadata=_PAGE)
    sort = ChoiceField(refs.COMMENT_SORT, load_default="asc", metadata={
        "description": "asc (oldest first, default), desc (newest first) or smart (VK's own order)"})
    comment = PositiveInt(metadata={
        "description": "a comment id: list the replies to that comment instead of the top-level thread"})


class VideosSearchSchema(BaseSchema):
    query = QueryField(metadata={"description": "text to search VK Video for"})
    page = PageField(max_page=MAX_SEARCH_PAGE, metadata=_PAGE)
    sort = ChoiceField(refs.VIDEO_SORT, metadata={"description": "relevant (default), latest or long"})
    content_type = ChoiceField(refs.VIDEO_CONTENT_TYPE, metadata={
        "description": "all (default), videos, clips or live"})
    duration = ChoiceField(refs.VIDEO_DURATION, metadata={"description": "any (default), long or short"})
    hd = Flag(load_default=False, metadata={"description": "true = high quality videos only"})


class VideoSchema(BaseSchema):
    video = VideoRefField(metadata={
        "description": "video id as <owner>_<video> (-22822305_456243154), video…/clip… form, or a vk.com / vkvideo.ru link"})


class VideoCommentsSchema(BaseSchema):
    video = VideoRefField(metadata={
        "description": "video id as <owner>_<video> (-22822305_456243154), video…/clip… form, or a vk.com / vkvideo.ru link"})
    page = PageField(max_page=MAX_PAGE, metadata=_PAGE)
    sort = ChoiceField(refs.VIDEO_COMMENT_SORT, load_default="desc", metadata={
        "description": "desc (newest first, default) or asc (oldest first)"})


class ArticleSchema(BaseSchema):
    article = ArticleRefField(metadata={
        "description": "article slug (@vk-verify) or a vk.com article link (https://vk.com/@vk-verify)"})
