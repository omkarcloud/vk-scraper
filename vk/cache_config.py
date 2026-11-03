"""Cache TTL per /vk/* endpoint (cache.py, keyed on the validated params).
Everything is public social data: profile cards and community pages move
slowly (name, bio, counters), walls and comment threads move within hours
on busy pages, and the signed media links VK hands out for videos / clips
expire after days, so nothing is held for more than a day.
"""
from datetime import timedelta

# A screen name -> id resolution never changes while the name exists.
RESOLVE_CACHE = timedelta(hours=24)
# Profile and community cards: bio / counters drift, 6 h keeps follower
# counts within a few percent on the busiest pages.
USER_CACHE = timedelta(hours=6)
COMMUNITY_CACHE = timedelta(hours=6)
# Walls (and the owner-scoped post search): new posts land hourly on
# active communities; one hour keeps page 1 fresh enough.
POSTS_CACHE = timedelta(hours=1)
POST_CACHE = timedelta(hours=1)
# Comment threads are the fastest-moving surface.
COMMENTS_CACHE = timedelta(minutes=30)
# Follower pages reorder as people follow; the total is in the user card too.
FOLLOWERS_CACHE = timedelta(hours=6)
# Member preview: 8 cards, mostly stable.
MEMBERS_CACHE = timedelta(hours=6)
# Video / clip lists and details carry signed CDN links that outlive this
# TTL by days; the view counts drift slowly.
VIDEOS_CACHE = timedelta(hours=6)
VIDEO_CACHE = timedelta(hours=6)
CLIPS_CACHE = timedelta(hours=6)
# Photo lists move only when the owner uploads.
PHOTOS_CACHE = timedelta(hours=12)
# Article lists and bodies: articles are rarely edited after publishing.
ARTICLES_CACHE = timedelta(hours=12)
ARTICLE_CACHE = timedelta(hours=24)
# Catalog search results: VK's own ranking is stable within a day.
SEARCH_CACHE = timedelta(hours=6)
