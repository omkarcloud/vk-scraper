"""Offline tests for the VK parsers against the captured fixtures
(vk/fixtures/, 2026-11-03; see parsers.py's docstring for what each one
is). Happy path, sparse / empty pages and the not-found shapes. No network.

    python -m pytest vk/test_parsers.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vk import parsers as P  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        if name.endswith(".json"):
            return json.load(f)["response"]
        return f.read()


# ---- value helpers ------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("10.10.1984", ("1984-10-10", "10-10")),
    ("1.3", (None, "03-01")),
    ("", (None, None)),
    (None, (None, None)),
    ("yesterday", (None, None)),
])
def test_birth_date(value, expected):
    assert P.birth_date(value) == expected


def test_image_sizes_sorted_and_cleaned():
    sizes = [{"type": "x", "width": 640, "height": 480, "url": "https://a/x.jpg"},
             {"type": "s", "width": 75, "height": 56, "url": "https://a/s.jpg"},
             {"type": "junk", "width": 1, "height": 1, "url": ""}]
    out = P.image_sizes(sizes)
    assert [s["type"] for s in out] == ["s", "x"]
    assert out[-1] == {"type": "x", "width": 640, "height": 480, "link": "https://a/x.jpg"}
    assert P.largest_image(sizes) == "https://a/x.jpg"
    assert P.largest_image(None) is None
    assert P.image_sizes("nope") == []


def test_bool_and_labels():
    assert P._bool(1) is True and P._bool(0) is False and P._bool(None) is None
    assert P._bool("true") is True and P._bool("maybe") is None
    assert P._label(P.SEX, 2) == "male" and P._label(P.SEX, "x") is None


# ---- users --------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def durov():
    return P.parse_user(fixture("user_durov.json")[0])


def test_user_identity(durov):
    assert durov["id"] == 1
    assert durov["name"] == "Pavel Durov"
    assert durov["screen_name"] == "durov"
    assert durov["link"] == "https://vk.com/durov"
    assert durov["is_verified"] is True
    assert durov["is_closed"] is False
    assert durov["deactivated"] is None
    assert durov["sex"] == "male"
    assert durov["birth_date"] == "1984-10-10"
    assert durov["city"] == {"id": 2, "name": "Saint Petersburg"}
    assert durov["country"] == {"id": 1, "name": "Russia"}
    assert durov["site"] == "http://t.me/durov"
    assert durov["followers_count"] > 4_000_000
    assert durov["photo"]["large"].startswith("https://")
    assert durov["photo"]["photo_link"] == "https://vk.com/photo1_456264771"


def test_user_bio_blocks(durov):
    assert durov["occupation"] == {"type": "work", "name": "Telegram", "id": None}
    assert durov["career"][0]["community_id"] == 22822305
    assert durov["career"][0]["from_year"] == 2006 and durov["career"][0]["until_year"] == 2014
    assert durov["career"][1]["company"] == "Telegram"
    assert durov["universities"][0]["name"] == "СПбГУ" and durov["universities"][0]["graduation_year"] == 2006
    assert durov["personal"]["political"] == "libertarian"
    assert "English" in durov["personal"]["languages"]
    assert durov["personal"]["smoking"] == "very negative"
    assert durov["interests"]["movies"] == "12 Angry Men"
    assert durov["interests"]["books"] is None          # "" -> null
    assert durov["wall"] == {"default_view": "owner", "visitors_can_post": False,
                             "comments_enabled": None, "can_see_all_posts": False}
    assert durov["relation"] is None                   # 0 -> null


def test_user_closed_and_deleted():
    closed = P.parse_user(fixture("user_closed.json")[0])
    assert closed["is_closed"] is True and closed["deactivated"] is None
    assert closed["name"] == "Alexandra Vladimirova"
    deleted = P.parse_user(fixture("user_deleted.json")[0])
    assert deleted["deactivated"] == "deleted"
    assert P.parse_user({})["id"] is None               # never crashes
    assert P.parse_user(None)["name"] is None


def test_profile_card_keeps_only_the_fields_present():
    card = P.profile_card({"id": 5, "first_name": "A", "last_name": "B", "is_closed": True})
    assert card["link"] == "https://vk.com/id5" and card["is_closed"] is True
    assert "city" not in card and "birth_date" not in card
    card = P.profile_card({"id": 5, "bdate": "1.2.2000", "online": 1, "last_seen": {"time": 1793696389, "platform": 4}})
    assert card["birth_date"] == "2000-02-01" and card["is_online"] is True
    assert card["last_seen"] == "2026-11-03T08:59:49Z" and card["last_seen_platform"] == "android"


# ---- communities ------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def vk_community():
    return P.parse_community(fixture("group_vk.json")["groups"][0], fixture("group_addresses.json")["items"])


def test_community_identity(vk_community):
    c = vk_community
    assert c["id"] == 22822305 and c["owner_id"] == -22822305
    assert c["name"] == "ВКонтакте" and c["screen_name"] == "vk"
    assert c["link"] == "https://vk.com/vk"
    assert c["type"] == "page" and c["access"] == "open"
    assert c["is_stub"] is False and c["deactivated"] is None
    assert c["is_verified"] is True
    assert c["members_count"] > 14_000_000
    assert c["description"].startswith("Это главное сообщество")
    assert c["status"] == "Социальная сеть"
    assert c["wall"] == "limited"
    assert c["cover"].startswith("https://") and len(c["cover_images"]) >= 3
    assert c["photo"]["large"].startswith("https://")


def test_community_blocks(vk_community):
    c = vk_community
    assert c["links"][0]["name"] == "FAQ" and c["links"][0]["link"].startswith("https://vk.ru/support")
    assert c["links"][1]["description"] == "О нас"
    assert c["contacts"][0]["email"] == "press@vk.com" and c["contacts"][0]["user_id"] is None
    assert c["menu"][0]["title"] == "VK Видео" and c["menu"][0]["cover"].startswith("https://")
    assert c["has_addresses"] is True
    address = c["addresses"][0]
    assert address["title"] == "Главный Штаб" and address["address"] == "Невский пр. 28"
    assert address["city"] == {"id": 2, "name": "Saint Petersburg"}
    assert address["latitude"] == pytest.approx(59.93562)
    assert address["open_status"] == "Working hours not provided"
    assert c["counters"] is None                        # [] -> null
    assert c["event"] is None and c["ban"] is None


def test_community_sparse_and_unknown():
    club1 = P.parse_community(fixture("group_club1.json")["groups"][0])
    assert club1["id"] == 1 and club1["screen_name"] == "club1" and club1["link"] == "https://vk.com/club1"
    assert club1["addresses"] == [] and club1["is_stub"] is False
    unknown = P.parse_community(fixture("group_unknown.json")["groups"][0])
    assert unknown["is_stub"] is True and unknown["name"] is None
    assert P.parse_community(None)["id"] is None


def test_community_card_from_search():
    cards, section_id, next_from = P.parse_community_search(fixture("search_groups.json"))
    assert len(cards) == 20 and section_id and next_from
    first = cards[0]
    assert first["name"] == "Python" and first["community_type"] == "group"
    assert first["link"] == "https://vk.com/python_django_programirovanie"
    assert first["owner_id"] == -first["id"]
    assert first["members_count"] > 70_000 and first["activity"] == "Programming"
    assert first["address"]["city"] == {"id": 2, "name": "Saint Petersburg"}
    assert first["is_verified"] is False and first["access"] == "open"
    page2, section_id2, next_from2 = P.parse_community_search(fixture("search_groups_page2.json"))
    # section ids embed the search's state, so a page captured in another
    # run carries its own; the API threads the id of the page before it
    assert len(page2) == 20 and section_id2 and next_from2 and next_from2 != next_from
    assert P.parse_community_search(fixture("search_groups_empty.json"))[0] == []
    assert P.parse_community_search(None) == ([], None, None)


# ---- walls ------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def wall():
    return P.parse_wall(fixture("wall_group.json"))


def test_wall_page(wall):
    posts, total = wall
    assert total == 1154 and len(posts) == 20
    post = posts[0]
    assert post["id"] == 1736006 and post["owner_id"] == -22822305
    assert post["link"] == "https://vk.com/wall-22822305_1736006"
    assert post["author"]["name"] == "ВКонтакте" and post["author"]["link"] == "https://vk.com/vk"
    assert post["author"]["type"] == "community"
    assert post["date"] == "2026-11-03T08:58:00Z"
    assert post["type"] == "post" and post["is_pinned"] is False and post["is_ad"] is False
    assert post["stats"]["likes"] == 136 and post["stats"]["comments"] == 17
    assert post["stats"]["reposts"] == 25 and post["stats"]["views"] == 1147
    assert post["stats"]["reactions"]["items"][0] == {"id": 0, "name": "Like", "count": 135}
    assert post["comments_enabled"] is True
    assert post["source"]["type"] == "vk"
    assert post["text"] is None                         # "" -> null
    assert post["repost_of"] == [] and post["geo"] is None


def test_wall_attachments(wall):
    posts, _ = wall
    kinds = {a["type"] for p in posts for a in p["attachments"]}
    assert kinds == {"video", "photo"}
    clip = next(a for p in posts for a in p["attachments"] if a["type"] == "video" and a["kind"] == "clip")
    assert clip["link"] == "https://vk.com/clip-22822305_456243517"
    assert clip["duration_seconds"] == 13 and clip["thumbnail"].startswith("https://")
    assert clip["stats"]["views"] > 0
    photo = next(a for p in posts for a in p["attachments"] if a["type"] == "photo")
    assert photo["link"] == "https://vk.com/photo-22822305_457379437"
    assert photo["width"] == 1920 and photo["image"].startswith("https://")
    assert photo["post_link"] == "https://vk.com/wall-22822305_1735059"
    assert len(photo["images"]) > 5


def test_user_wall_and_reactions():
    posts, total = P.parse_wall(fixture("wall_user.json"))
    assert total == 1020 and len(posts) == 10
    post = posts[0]
    assert post["author"] == {"id": 1, "type": "user", "name": "Pavel Durov", "screen_name": "durov",
                              "link": "https://vk.com/durov", "photo": post["author"]["photo"], "is_verified": None}
    assert post["edited"] == "2018-05-08T21:10:26Z"
    names = {r["name"] for r in post["stats"]["reactions"]["items"]}
    assert {"Like", "Haha", "Wow!", "Love", "Sad"} <= names
    assert post["stats"]["views"] > 15_000_000
    assert post["text"].startswith("Иногда говорят")


def test_wall_past_end_and_junk():
    assert P.parse_wall(fixture("wall_past_end.json")) == ([], 1154)
    assert P.parse_wall(None) == ([], None)
    assert P.parse_wall({"items": [None, "x", {}]})[0][2]["id"] is None


def test_wall_search():
    posts, total = P.parse_wall(fixture("wall_search.json"))
    assert total == 19 and len(posts) == 19
    # the owner-scoped search still surfaces one post VK attributes to
    # another community (a shared post), so the owner varies per item
    assert sum(p["link"].startswith("https://vk.com/wall-22822305_") for p in posts) == 18
    assert all(p["link"].startswith("https://vk.com/wall") for p in posts)


def test_wall_search_drops_comments_and_reports_page_size():
    # captured without owners_only: VK mixes matching comments (post_type
    # "reply") into the hits, 17 of 19 here; only the 2 posts survive
    posts, page_size = P.parse_wall_search(fixture("wall_search.json"))
    assert page_size == 19 and len(posts) == 2
    assert all(p["type"] == "post" for p in posts)
    # on a user's wall every hit was a visitor's comment
    posts, page_size = P.parse_wall_search(fixture("wall_search_user_replies.json"))
    assert page_size == 10 and posts == []
    assert P.parse_wall_search(None) == ([], 0)


def test_post_by_id_and_deleted():
    post = P.parse_post_by_id(fixture("post_by_id.json"))
    assert post["id"] == 1736006 and post["is_deleted"] is False
    assert post["stats"]["likes"] == 136
    deleted = P.parse_post_by_id(fixture("post_unknown.json"))
    assert deleted["is_deleted"] is True and deleted["deleted_reason"] == "Post deleted"
    assert P.parse_post_by_id({"items": []}) is None
    assert P.parse_post_by_id(None) is None


def test_attachment_shapes():
    link = P.parse_attachment({"type": "link", "link": {"url": "https://t.me/x", "title": "T", "caption": "t.me",
                                                       "description": "d", "photo": {"sizes": [{"type": "x", "width": 1, "height": 1, "url": "https://i/x.jpg"}]}}})
    assert link == {"type": "link", "link": "https://t.me/x", "title": "T", "caption": "t.me", "description": "d",
                    "image": "https://i/x.jpg", "button": None}
    doc = P.parse_attachment({"type": "doc", "doc": {"id": 1, "owner_id": 2, "title": "a.pdf", "ext": "pdf", "size": 10,
                                                     "url": "https://d/a.pdf", "date": 1793696389}})
    assert doc["type"] == "document" and doc["size_bytes"] == 10 and doc["date"] == "2026-11-03T08:59:49Z"
    poll = P.parse_attachment({"type": "poll", "poll": {"id": 1, "question": "Q?", "votes": 3, "anonymous": True,
                                                        "answers": [{"id": 1, "text": "a", "votes": 3, "rate": 100.0}]}})
    assert poll["is_anonymous"] is True and poll["answers"][0]["rate_pct"] == 100.0
    audio = P.parse_attachment({"type": "audio", "audio": {"id": 1, "owner_id": 2, "artist": "A", "title": "T", "duration": 61}})
    assert audio["duration_seconds"] == 61 and audio["link"] is None
    sticker = P.parse_attachment({"type": "sticker", "sticker": {"sticker_id": 7, "product_id": 1, "images": [{"url": "https://s/7", "width": 64, "height": 64}]}})
    assert sticker == {"type": "sticker", "id": 7, "product_id": 1, "image": "https://s/7", "animation": None}
    product = P.parse_attachment({"type": "market", "market": {"id": 3, "owner_id": -4, "title": "Mug",
                                                               "price": {"amount": "150000", "currency": {"name": "RUB"}, "text": "1 500 ₽"}}})
    assert product["price"] == 1500.0 and product["currency"] == "RUB"
    assert product["link"] == "https://vk.com/market-4?w=product-4_3"
    other = P.parse_attachment({"type": "album", "album": {"id": 9, "owner_id": 1, "title": "Trip"}})
    assert other == {"type": "album", "id": 9, "owner_id": 1, "title": "Trip", "link": None, "image": None}
    assert P.parse_attachment({"type": "photo"})["id"] is None
    assert P.parse_attachment(None) is None
    assert P.parse_attachments("junk") == []


def test_repost_history_is_parsed():
    raw = {"id": 1, "owner_id": 1, "from_id": 1, "text": "look", "copy_history": [
        {"id": 2, "owner_id": -5, "from_id": -5, "text": "original", "attachments": []}]}
    post = P.parse_post(raw, {-5: P.community_card({"id": 5, "name": "G", "screen_name": "g"})})
    assert post["repost_of"][0]["link"] == "https://vk.com/wall-5_2"
    assert post["repost_of"][0]["author"]["name"] == "G"


def test_geo_and_copyright():
    post = P.parse_post({"id": 1, "owner_id": 1, "geo": {"type": "point", "coordinates": "59.93 30.32",
                                                         "place": {"id": 7, "title": "Nevsky", "city": "SPb"}},
                         "copyright": {"link": "https://x.y/z", "name": "X", "type": "link"}, "signer_id": 9})
    assert post["geo"]["latitude"] == pytest.approx(59.93) and post["geo"]["place"]["title"] == "Nevsky"
    assert post["copyright"]["name"] == "X"
    assert post["signer"]["link"] == "https://vk.com/id9"


# ---- comments ---------------------------------------------------------------------------------

def test_post_comments():
    comments, top_level, total = P.parse_comments(fixture("post_comments.json"), -22822305, 1736006)
    assert (top_level, total, len(comments)) == (16, 17, 16)
    first = comments[0]
    assert first["post_id"] == 1736006 and first["owner_id"] == -22822305
    assert first["link"] == "https://vk.com/wall-22822305_1736006?reply=1736007"
    assert first["author"]["link"].startswith("https://vk.com/")
    assert first["date"] == "2026-11-03T08:59:49Z"
    assert first["attachments"][0]["type"] == "sticker"
    threaded = next(c for c in comments if c["replies"] and c["replies"]["count"])
    assert threaded["text"].startswith("Куда пропал")
    reply = threaded["replies"]["items"][0]
    assert reply["is_from_post_author"] is True
    assert reply["reply_to"]["comment_id"] == threaded["id"]
    assert reply["reply_to"]["user"]["name"] == threaded["author"]["name"]
    assert reply["parent_ids"] == [threaded["id"]]
    assert reply["author"]["type"] == "community"


def test_comment_replies_and_junk():
    replies, top_level, total = P.parse_comments(fixture("post_comment_replies.json"), -22822305, 1736006)
    assert top_level == 1 and len(replies) == 1 and replies[0]["author"]["name"] == "ВКонтакте"
    assert P.parse_comments(None) == ([], None, None)
    assert P.parse_comment({})["id"] is None


def test_video_comments():
    comments, top_level, total = P.parse_comments(fixture("video_comments.json"), 1, 456239023)
    assert (top_level, total, len(comments)) == (145, 177, 50)
    assert comments[0]["author"]["name"] == "Alex Lazarev"
    assert all(c["date"] for c in comments)


# ---- followers / members -----------------------------------------------------------------------

def test_followers_and_members():
    cards, total = P.parse_cards(fixture("followers.json"))
    assert total > 4_000_000 and len(cards) == 50
    assert cards[0]["name"] == "Matvei Fff" and cards[0]["link"] == "https://vk.com/matvei4304f"
    assert cards[0]["is_closed"] is True and cards[0]["is_online"] is False
    members, total = P.parse_cards(fixture("members_preview.json"))
    assert total > 14_000_000 and len(members) == 8
    assert members[0]["city"] == {"id": 2, "name": "Saint Petersburg"} and members[0]["photo"] is None
    assert P.parse_cards({"items": [1, 2]}) == ([], None)


# ---- videos / clips -------------------------------------------------------------------------------

def test_video_list():
    videos, total = P.parse_videos(fixture("videos_group.json"))
    assert total == 95 and len(videos) == 20
    video = videos[0]
    assert video["id"] == 456243492 and video["owner_id"] == -22822305
    assert video["link"] == "https://vk.com/video-22822305_456243492"
    assert video["vkvideo_link"].startswith("https://vkvideo.ru/video-22822305_456243492")
    assert video["kind"] == "video" and video["title"] == "С Днём отца! | VK"
    assert video["author"]["name"] == "ВКонтакте" and video["author"]["is_verified"] is True
    assert video["date"] == "2026-10-16T10:15:48Z"
    assert video["duration_seconds"] == 224 and (video["width"], video["height"]) == (3840, 2160)
    assert video["stats"] == {"views": 1024605, "likes": 1027, "comments": 3, "reposts": 29}
    assert video["downloads"][0]["quality"] == 2160 and video["downloads"][-1]["quality"] == 144
    assert all(d["format"] == "mp4" and d["link"].startswith("https://") for d in video["downloads"])
    assert set(video["streams"]) == {"dash_sep", "dash_webm", "dash_webm_av1", "hls", "hls_fmp4"}
    assert video["subtitles"][0]["language"] == "ru" and video["subtitles"][0]["is_auto"] is True
    assert video["post_link"] == "https://vk.com/wall-22822305_1730372"
    assert video["is_downloadable"] is False and video["trailer"].startswith("https://")
    assert video["player_link"].startswith("https://vkvideo.ru/video_ext.php")


def test_video_by_id_and_unknown():
    assert P.parse_video_by_id(fixture("video_by_id.json"))["title"] == "ВКонтакте 19 лет"
    assert P.parse_video_by_id(fixture("video_unknown.json")) is None
    assert P.parse_video_by_id({"items": []}) is None
    assert P.parse_video(None)["id"] is None


def test_clips():
    clips, total, next_from = P.parse_clips(fixture("clips_group.json"))
    assert total == 84 and len(clips) == 20 and next_from
    clip = clips[0]
    assert clip["kind"] == "clip" and clip["link"] == "https://vk.com/clip-22822305_456243518"
    assert clip["description"].startswith("Ко Дню народного единства")
    assert clip["author"]["screen_name"] == "vk"
    assert clip["action_button"]["title"] == "Отправить подарок"
    assert clip["loops"] is True and clip["downloads"][0]["quality"] == 1080
    assert P.parse_video_by_id(fixture("clip_by_id.json"))["kind"] == "clip"
    assert P.parse_clips(fixture("clips_user_empty.json")) == ([], 0, None)


# ---- photos / articles ----------------------------------------------------------------------------

def test_photos():
    photos, total = P.parse_photos(fixture("photos_wall_group.json"))
    assert total == 1590 and len(photos) == 50
    photo = photos[0]
    assert photo["link"] == "https://vk.com/photo-22822305_457379437"
    assert photo["album_id"] == -7 and photo["date"] == "2026-10-30T19:43:56Z"
    assert photo["image"].startswith("https://") and photo["width"] == 1920
    assert photo["stats"]["likes"] == 221 and photo["can_comment"] is True
    assert photo["post_link"] == "https://vk.com/wall-22822305_1735059"
    assert photo["uploader_id"] is None                 # 100 = the community itself
    photos, total = P.parse_photos(fixture("photos_all_group.json"))
    assert total == 9 and len(photos) == 9
    assert P.parse_photos(None) == ([], None)


def test_articles():
    articles, total = P.parse_articles(fixture("articles_group.json"))
    assert total == 26 and len(articles) == 20
    article = articles[0]
    assert article["id"] == 217146 and article["title"] == "Верификация ВКонтакте: новые критерии"
    assert article["slug"] == "vk-verify" and article["link"] == "https://vk.ru/@vk-verify"
    assert article["author"]["name"] == "ВКонтакте"
    assert article["published"] == "2023-09-28T10:37:37Z"
    assert article["stats"] == {"views": 241585, "shares": 1491}
    assert article["reading_time_seconds"] == 101 and article["image"].startswith("https://")
    assert article["lead"].startswith("от 28 апреля 2025 года")
    assert P.parse_articles(fixture("articles_user_empty.json")) == ([], 0)


def test_article_page():
    article = P.parse_article_page(fixture("article_page.html"), "vk-verify")
    assert article["id"] == 217146 and article["owner_id"] == -22822305
    assert article["link"] == "https://vk.com/@vk-verify"
    assert article["title"] == "Верификация ВКонтакте: новые критерии"
    assert article["subtitle"] == "от 28 апреля 2025 года"
    assert article["author"] == {"id": -22822305, "name": "ВКонтакте", "type": "community",
                                 "link": "https://vk.com/club22822305"}
    assert article["published"] == "2023-09-28T10:37:37Z"
    assert article["modified"] == "2026-09-04T12:44:14Z"
    assert article["image"].startswith("http")
    assert article["views"] == 241585
    assert article["headings"][0] == {"level": 3, "text": "Как получить верификацию?"}
    assert "не меньше 5 тысяч подписчиков" in article["text"]
    assert article["text"].startswith("от 28 апреля 2025 года")
    assert article["word_count"] > 1000
    assert {"link": "https://dobro.mail.ru/funds/registration/", "text": "VK Добро"} in article["links"]
    assert not any("/away.php" in l["link"] for l in article["links"])


def test_article_page_without_body():
    article = P.parse_article_page(fixture("article_404.html"), "nope")
    assert article["id"] is None and article["text"] is None and article["title"] is None
    assert P.parse_article_page(None, "x")["word_count"] == 0


# ---- video search ----------------------------------------------------------------------------------

def test_video_search():
    videos, playlists, section_id, next_from = P.parse_video_search(fixture("search_videos.json"))
    assert len(videos) == 31 and len(playlists) == 10 and section_id and next_from
    assert len({f"{v['owner_id']}_{v['id']}" for v in videos}) == 31
    first = videos[0]
    assert first["kind"] == "video" and first["author"]["name"] == "Python Russian"
    assert first["link"].startswith("https://vk.com/video-")
    playlist = playlists[0]
    assert playlist["title"] == "Python для начинающих" and playlist["videos_count"] == 25
    assert playlist["link"] == "https://vkvideo.ru/playlist/-194554202_13"
    assert playlist["updated"] == "2024-11-25T08:47:40Z"
    page2 = P.parse_video_search(fixture("search_videos_page2.json"))
    assert len(page2[0]) == 10 and page2[1] == [] and page2[2] and page2[3]
    assert P.parse_video_search(None) == ([], [], None, None)
