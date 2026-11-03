"""VK API JSON (and the one server-rendered article page) -> clean dicts.
Pure functions, no I/O; every helper tolerates None and junk.

Fixtures (vk/fixtures/, captured 2026-11-03 through the anonymous web token,
API v5.289): users.get for Pavel Durov (user_durov.json), a closed profile
(user_closed.json) and a deleted id (user_deleted.json); groups.getById for
the VK community (group_vk.json), club1 (group_club1.json) and an unknown
id (group_unknown.json); groups.getAddresses (group_addresses.json);
wall.get for the community (wall_group.json) and Durov (wall_user.json) and
past the end (wall_past_end.json); wall.getById (post_by_id.json,
post_unknown.json = a deleted post); wall.getComments (post_comments.json,
post_comment_replies.json); wall.search (wall_search.json); users.getFollowers
(followers.json); groups.getMembers (members_preview.json); video.get lists
and single videos (videos_group.json, video_by_id.json, video_unknown.json =
a stub for an id that does not exist); video.getComments
(video_comments.json); shortVideo.getOwnerVideos (clips_group.json,
clips_user_empty.json) and one clip through video.get (clip_by_id.json);
photos.getAll / photos.get (photos_all_group.json, photos_wall_group.json);
articles.getOwnerPublished (articles_group.json, articles_user_empty.json);
catalog.getSearchGroups (search_groups.json, search_groups_empty.json) and
its catalog.getSection page 2 (search_groups_page2.json);
catalog.getVideoSearch (search_videos.json) and its page 2
(search_videos_page2.json); the vk.ru/@vk-verify article page
(article_page.html) and a 404 (article_404.html), both trimmed to their HTML
and ld+json (VK's inline scripts, styles and SVG icons removed).

Conventions of the records: identity first (id, name, link), then content,
then stats, then nested objects, metadata last; dates ISO-8601 UTC; absent
values null; VK's tracking / presentation fields (track_code, hash, badges,
ads_easy_promote, attachments_meta, push_subscription, header, stats_pixels,
tracking_info, timeline_thumbs, response_type, ov_id, can_* flags) dropped.
"""
import html as html_lib
import json
import re

from himalayas.shared import epoch_to_iso
from seek.shared import as_dict, as_list, g, html_to_text, text, to_int
from vk import refs

# ---- code tables (dev.vk.com/reference/objects/user) ---------------------------------------

SEX = {1: "female", 2: "male"}
RELATION = {1: "single", 2: "in a relationship", 3: "engaged", 4: "married", 5: "it's complicated",
            6: "actively searching", 7: "in love", 8: "in a civil union"}
POLITICAL = {1: "communist", 2: "socialist", 3: "moderate", 4: "liberal", 5: "conservative",
             6: "monarchist", 7: "ultraconservative", 8: "indifferent", 9: "libertarian"}
PEOPLE_MAIN = {1: "intellect and creativity", 2: "kindness and honesty", 3: "health and beauty",
               4: "wealth and power", 5: "courage and persistence", 6: "humor and love for life"}
LIFE_MAIN = {1: "family and children", 2: "career and money", 3: "entertainment and leisure",
             4: "science and research", 5: "improving the world", 6: "personal development",
             7: "beauty and art", 8: "fame and influence"}
ATTITUDE = {1: "very negative", 2: "negative", 3: "neutral", 4: "compromisable", 5: "positive"}
PLATFORM = {1: "mobile", 2: "iphone", 3: "ipad", 4: "android", 5: "windows phone", 6: "windows", 7: "web"}
GROUP_ACCESS = {0: "open", 1: "closed", 2: "private"}
WALL_MODE = {0: "disabled", 1: "open", 2: "limited", 3: "closed"}
AGE_LIMITS = {1: "none", 2: "16+", 3: "18+"}
OCCUPATION_TYPE = {"work": "work", "school": "school", "university": "university"}
MAIN_SECTION = {0: None, 1: "photos", 2: "topics", 3: "audio", 4: "videos", 5: "market", 6: "articles"}


# ---- value helpers ------------------------------------------------------------------------------

def _bool(value):
    """VK's 0/1 / true/false flags -> bool; missing -> None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    low = str(value).strip().lower()
    if low in ("1", "true", "yes"):
        return True
    if low in ("0", "false", "no", ""):
        return False
    return None


def _label(table, value):
    code = to_int(value)
    return table.get(code) if code is not None else None


def _link(value):
    value = text(value)
    return value if value and value.startswith(("http://", "https://")) else None


def _count(value):
    """A counter that may come as an int or as {"count": n}."""
    if isinstance(value, dict):
        value = value.get("count")
    return to_int(value)


def birth_date(bdate):
    """VK's 'DD.MM.YYYY' / 'DD.MM' -> ('YYYY-MM-DD' | None, 'MM-DD' | None)."""
    value = text(bdate)
    if not value:
        return None, None
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?", value)
    if not match:
        return None, None
    day, month, year = int(match.group(1)), int(match.group(2)), match.group(3)
    day_month = f"{month:02d}-{day:02d}"
    return (f"{year}-{month:02d}-{day:02d}" if year else None), day_month


def image_sizes(sizes):
    """VK's size list [{type, width, height, url}] -> [{type, width, height,
    link}] smallest first, dropping entries without a link."""
    out = []
    for size in as_list(sizes):
        link = _link(g(size, "url"))
        if not link:
            continue
        out.append({"type": text(g(size, "type")), "width": to_int(g(size, "width")),
                    "height": to_int(g(size, "height")), "link": link})
    out.sort(key=lambda s: (s["width"] or 0, s["height"] or 0))
    return out


def largest_image(sizes):
    images = image_sizes(sizes)
    return images[-1]["link"] if images else None


def _place(value):
    """A city / country {id, title} -> {id, name} | None."""
    value = as_dict(value)
    if not value:
        return None
    return {"id": to_int(value.get("id")), "name": text(value.get("title"))}


# ---- people (profiles + groups that ride along in `extended` responses) --------------------------

def profile_card(raw):
    """A user as VK returns it in `profiles` lists / followers / members."""
    raw = as_dict(raw)
    user_id = to_int(raw.get("id"))
    screen_name = text(raw.get("screen_name")) or text(raw.get("domain"))
    first, last = text(raw.get("first_name")), text(raw.get("last_name"))
    name = " ".join(p for p in (first, last) if p) or None
    date, day = birth_date(raw.get("bdate"))
    last_seen = as_dict(raw.get("last_seen"))
    card = {
        "id": user_id,
        "type": "user",
        "name": name,
        "first_name": first,
        "last_name": last,
        "screen_name": screen_name,
        "link": refs.owner_link(user_id, screen_name),
        "photo": _link(raw.get("photo_200")) or _link(raw.get("photo_100")) or _link(raw.get("photo_50")),
        "is_verified": _bool(raw.get("verified")),
        "is_closed": _bool(raw.get("is_closed")),
        "deactivated": text(raw.get("deactivated")),
    }
    for key, value in (("sex", _label(SEX, raw.get("sex"))),
                       ("city", _place(raw.get("city"))),
                       ("country", _place(raw.get("country"))),
                       ("birth_date", date), ("birth_day", day),
                       ("followers_count", to_int(raw.get("followers_count"))),
                       ("is_online", _bool(raw.get("online"))),
                       ("last_seen", epoch_to_iso(last_seen.get("time"))),
                       ("last_seen_platform", _label(PLATFORM, last_seen.get("platform")))):
        if key in raw or (key in ("birth_date", "birth_day") and "bdate" in raw) \
                or (key.startswith("last_seen") and last_seen) or (key == "is_online" and "online" in raw):
            card[key] = value
    return card


def community_card(raw):
    """A community as VK returns it in `groups` lists / search results."""
    raw = as_dict(raw)
    group_id = to_int(raw.get("id"))
    screen_name = text(raw.get("screen_name"))
    main_address = g(raw, "addresses", "main_address")
    card = {
        "id": group_id,
        "owner_id": -group_id if group_id is not None else None,
        "type": "community",
        "community_type": text(raw.get("type")),
        "name": text(raw.get("name")),
        "screen_name": screen_name,
        "link": refs.owner_link(-group_id if group_id is not None else None, screen_name),
        "photo": _link(raw.get("photo_200")) or _link(raw.get("photo_100")) or _link(raw.get("photo_50")),
        "activity": text(raw.get("activity")),
        "is_verified": _bool(raw.get("verified")),
        "access": _label(GROUP_ACCESS, raw.get("is_closed")),
        "deactivated": text(raw.get("deactivated")),
    }
    if "members_count" in raw:
        card["members_count"] = to_int(raw.get("members_count"))
    if "trending" in raw:
        card["is_trending"] = _bool(raw.get("trending"))
    if "is_government_organization" in raw:
        card["is_government_organization"] = _bool(raw.get("is_government_organization"))
    if isinstance(main_address, dict):
        card["address"] = {
            "title": text(main_address.get("title")),
            "address": text(main_address.get("address")),
            "city": _place(main_address.get("city")),
            "country": _place(main_address.get("country")),
        }
    elif "addresses" in raw:
        card["address"] = None
    return card


def people_index(response):
    """{owner_id: card} for the `profiles` (positive ids) and `groups`
    (negative ids) that an extended response carries."""
    index = {}
    for raw in as_list(g(response, "profiles")):
        card = profile_card(raw)
        if card["id"] is not None:
            index[card["id"]] = card
    for raw in as_list(g(response, "groups")):
        card = community_card(raw)
        if card["id"] is not None:
            index[-card["id"]] = card
    return index


def author_card(owner_id, index):
    """The compact author block for posts / comments / videos."""
    owner_id = to_int(owner_id)
    if owner_id is None:
        return None
    card = index.get(owner_id) if index else None
    if card is None:
        return {"id": owner_id, "type": "community" if owner_id < 0 else "user", "name": None,
                "screen_name": None, "link": refs.owner_link(owner_id), "photo": None,
                "is_verified": None}
    return {"id": owner_id, "type": card["type"], "name": card["name"], "screen_name": card["screen_name"],
            "link": card["link"], "photo": card["photo"], "is_verified": card["is_verified"]}


# ---- users ----------------------------------------------------------------------------------------

def _career(items):
    out = []
    for item in as_list(items):
        item = as_dict(item)
        community_id = to_int(item.get("group_id"))
        out.append({
            "company": text(item.get("company")),
            "community_id": community_id,
            "community_link": refs.owner_link(-community_id) if community_id else None,
            "position": text(item.get("position")),
            "from_year": to_int(item.get("from")),
            "until_year": to_int(item.get("until")),
            "city_id": to_int(item.get("city_id")),
            "country_id": to_int(item.get("country_id")),
        })
    return out


def _universities(items):
    out = []
    for item in as_list(items):
        item = as_dict(item)
        out.append({
            "id": to_int(item.get("id")),
            "name": text(item.get("name")),
            "faculty": text(item.get("faculty_name")),
            "chair": text(item.get("chair_name")),
            "graduation_year": to_int(item.get("graduation")),
            "education_form": text(item.get("education_form")),
            "education_status": text(item.get("education_status")),
            "city_id": to_int(item.get("city")),
            "country_id": to_int(item.get("country")),
        })
    return out


def _schools(items):
    out = []
    for item in as_list(items):
        item = as_dict(item)
        out.append({
            "id": text(item.get("id")),
            "name": text(item.get("name")),
            "type": text(item.get("type_str")),
            "class": text(item.get("class")),
            "speciality": text(item.get("speciality")),
            "year_from": to_int(item.get("year_from")),
            "year_to": to_int(item.get("year_to")),
            "year_graduated": to_int(item.get("year_graduated")),
            "city_id": to_int(item.get("city")),
            "country_id": to_int(item.get("country")),
        })
    return out


def _military(items):
    out = []
    for item in as_list(items):
        item = as_dict(item)
        out.append({"unit": text(item.get("unit")), "unit_id": to_int(item.get("unit_id")),
                    "from_year": to_int(item.get("from")), "until_year": to_int(item.get("until")),
                    "country_id": to_int(item.get("country_id"))})
    return out


def _relatives(items):
    out = []
    for item in as_list(items):
        item = as_dict(item)
        user_id = to_int(item.get("id"))
        out.append({"id": user_id if user_id and user_id > 0 else None, "name": text(item.get("name")),
                    "type": text(item.get("type")),
                    "link": refs.owner_link(user_id) if user_id and user_id > 0 else None})
    return out


def _personal(raw):
    raw = as_dict(raw)
    if not raw:
        return None
    return {
        "political": _label(POLITICAL, raw.get("political")),
        "languages": [text(x) for x in as_list(raw.get("langs")) if text(x)],
        "religion": text(raw.get("religion")),
        "inspired_by": text(raw.get("inspired_by")),
        "people_main": _label(PEOPLE_MAIN, raw.get("people_main")),
        "life_main": _label(LIFE_MAIN, raw.get("life_main")),
        "smoking": _label(ATTITUDE, raw.get("smoking")),
        "alcohol": _label(ATTITUDE, raw.get("alcohol")),
    }


def parse_user(raw):
    """users.get element -> the profile record. A deleted / banned id comes
    back with `deactivated` set ("deleted" / "banned") and VK's placeholder
    name; the API turns that into a 404."""
    raw = as_dict(raw)
    card = profile_card(raw)
    date, day = birth_date(raw.get("bdate"))
    last_seen = as_dict(raw.get("last_seen"))
    occupation = as_dict(raw.get("occupation"))
    relation_partner = as_dict(raw.get("relation_partner"))
    partner_id = to_int(relation_partner.get("id"))
    return {
        "id": card["id"],
        "name": card["name"],
        "first_name": card["first_name"],
        "last_name": card["last_name"],
        "maiden_name": text(raw.get("maiden_name")),
        "nickname": text(raw.get("nickname")),
        "screen_name": card["screen_name"],
        "link": card["link"],
        "deactivated": card["deactivated"],
        "is_verified": card["is_verified"],
        "is_closed": card["is_closed"],
        "is_online": _bool(raw.get("online")),
        "last_seen": epoch_to_iso(last_seen.get("time")),
        "last_seen_platform": _label(PLATFORM, last_seen.get("platform")),
        "status": text(raw.get("status")),
        "about": text(raw.get("about")),
        "site": text(raw.get("site")),
        "sex": _label(SEX, raw.get("sex")),
        "birth_date": date,
        "birth_day": day,
        "city": _place(raw.get("city")),
        "country": _place(raw.get("country")),
        "home_town": text(raw.get("home_town")),
        "followers_count": to_int(raw.get("followers_count")),
        "photo": {
            "small": _link(raw.get("photo_50")),
            "medium": _link(raw.get("photo_100")),
            "large": _link(raw.get("photo_200")),
            "original": _link(raw.get("photo_max_orig")) or _link(raw.get("photo_400_orig")) or _link(raw.get("photo_max")),
            "photo_id": text(raw.get("photo_id")),
            "photo_link": refs.photo_link(*text(raw.get("photo_id")).split("_")) if re.fullmatch(r"-?\d+_\d+", text(raw.get("photo_id")) or "") else None,
        },
        "has_cover": _bool(g(raw, "cover", "enabled")),
        "occupation": {
            "type": text(occupation.get("type")),
            "name": text(occupation.get("name")),
            "id": to_int(occupation.get("id")),
        } if occupation else None,
        "career": _career(raw.get("career")),
        "universities": _universities(raw.get("universities")),
        "schools": _schools(raw.get("schools")),
        "military": _military(raw.get("military")),
        "relation": _label(RELATION, raw.get("relation")),
        "relation_partner": {"id": partner_id, "name": " ".join(p for p in (text(relation_partner.get("first_name")), text(relation_partner.get("last_name"))) if p) or None,
                             "link": refs.owner_link(partner_id)} if partner_id else None,
        "relatives": _relatives(raw.get("relatives")),
        "personal": _personal(raw.get("personal")),
        "interests": {
            "activities": text(raw.get("activities")),
            "interests": text(raw.get("interests")),
            "music": text(raw.get("music")),
            "movies": text(raw.get("movies")),
            "tv": text(raw.get("tv")),
            "books": text(raw.get("books")),
            "games": text(raw.get("games")),
            "quotes": text(raw.get("quotes")),
        },
        "wall": {
            "default_view": text(raw.get("wall_default")),
            "visitors_can_post": _bool(raw.get("can_post")),
            "comments_enabled": _bool(raw.get("wall_comments")),
            "can_see_all_posts": _bool(raw.get("can_see_all_posts")),
        },
        "can_write_private_message": _bool(raw.get("can_write_private_message")),
        "is_nft_avatar": _bool(raw.get("is_nft")),
        "is_trending": _bool(raw.get("trending")),
    }


# ---- communities ------------------------------------------------------------------------------

def _community_links(items):
    out = []
    for item in as_list(items):
        item = as_dict(item)
        out.append({"id": to_int(item.get("id")), "name": text(item.get("name")),
                    "description": text(item.get("desc")), "link": _link(item.get("url")),
                    "photo": _link(item.get("photo_100")) or _link(item.get("photo_50"))})
    return out


def _community_contacts(items):
    out = []
    for item in as_list(items):
        item = as_dict(item)
        user_id = to_int(item.get("user_id"))
        out.append({"user_id": user_id, "link": refs.owner_link(user_id) if user_id else None,
                    "description": text(item.get("desc")), "phone": text(item.get("phone")),
                    "email": text(item.get("email"))})
    return out


def _menu(raw):
    out = []
    for item in as_list(g(raw, "items")):
        item = as_dict(item)
        out.append({"id": to_int(item.get("id")), "title": text(item.get("title")),
                    "type": text(item.get("type")), "link": _link(item.get("url")),
                    "cover": largest_image(item.get("cover"))})
    return out


def _counters(raw):
    raw = as_dict(raw)
    out = {k: to_int(v) for k, v in raw.items() if to_int(v) is not None}
    return out or None


def parse_address(raw):
    raw = as_dict(raw)
    open_status = as_dict(raw.get("open_status"))
    return {
        "id": to_int(raw.get("id")),
        "title": text(raw.get("title")),
        "address": text(raw.get("address")),
        "additional_address": text(raw.get("additional_address")),
        "city": _place(raw.get("city")) or ({"id": to_int(raw.get("city_id")), "name": None} if raw.get("city_id") else None),
        "country": _place(raw.get("country")) or ({"id": to_int(raw.get("country_id")), "name": None} if raw.get("country_id") else None),
        "metro_station": _place(raw.get("metro_station")) if isinstance(raw.get("metro_station"), dict) else None,
        "latitude": raw.get("latitude") if isinstance(raw.get("latitude"), (int, float)) else None,
        "longitude": raw.get("longitude") if isinstance(raw.get("longitude"), (int, float)) else None,
        "phone": text(raw.get("phone")),
        "work_status": text(raw.get("work_info_status")),
        "open_status": text(open_status.get("primary_text")) if open_status else None,
        "timetable": raw.get("timetable") if isinstance(raw.get("timetable"), dict) else None,
        "time_offset_minutes": to_int(raw.get("time_offset")),
    }


def parse_community(raw, addresses=None):
    """groups.getById element (+ groups.getAddresses items) -> the community
    record. An unknown id answers a stub (empty name, 0 members, 'Private
    community' activity): `is_stub` flags it and the API turns it into a 404."""
    raw = as_dict(raw)
    card = community_card(raw)
    place = as_dict(raw.get("place"))
    ban = as_dict(raw.get("ban_info"))
    address_list = [parse_address(a) for a in as_list(addresses)]
    return {
        "id": card["id"],
        "owner_id": card["owner_id"],
        "name": card["name"],
        "screen_name": card["screen_name"],
        "link": card["link"],
        "type": card["community_type"],
        "activity": card["activity"],
        "description": html_to_text(raw.get("description")),
        "status": text(raw.get("status")),
        "access": card["access"],
        "deactivated": card["deactivated"],
        "is_stub": not card["name"] and not to_int(raw.get("members_count")) and not _bool(raw.get("has_photo")),
        "is_verified": card["is_verified"],
        "is_trending": _bool(raw.get("trending")),
        "is_government_organization": _bool(raw.get("is_government_organization")),
        "members_count": to_int(raw.get("members_count")),
        "site": _link(raw.get("site")) or text(raw.get("site")),
        "city": _place(raw.get("city")),
        "country": _place(raw.get("country")),
        "photo": {
            "small": _link(raw.get("photo_50")),
            "medium": _link(raw.get("photo_100")),
            "large": _link(raw.get("photo_200")),
            "original": _link(raw.get("photo_max_orig")),
        },
        "cover": largest_image(g(raw, "cover", "images")) if _bool(g(raw, "cover", "enabled")) else None,
        "cover_images": image_sizes(g(raw, "cover", "images")),
        "wall": _label(WALL_MODE, raw.get("wall")),
        "age_limit": _label(AGE_LIMITS, raw.get("age_limits")),
        "main_section": _label(MAIN_SECTION, raw.get("main_section")),
        "pinned_post_id": to_int(raw.get("fixed_post")),
        "pinned_post_link": refs.post_link(card["owner_id"], to_int(raw.get("fixed_post"))) if to_int(raw.get("fixed_post")) else None,
        "public_date_label": text(raw.get("public_date_label")),
        "event": {
            "start": epoch_to_iso(raw.get("start_date")),
            "finish": epoch_to_iso(raw.get("finish_date")),
        } if raw.get("start_date") or raw.get("finish_date") else None,
        "place": {
            "id": to_int(place.get("id")), "title": text(place.get("title")),
            "address": text(place.get("address")), "latitude": place.get("latitude"),
            "longitude": place.get("longitude"),
        } if place else None,
        "links": _community_links(raw.get("links")),
        "contacts": _community_contacts(raw.get("contacts")),
        "menu": _menu(raw.get("menu")),
        "addresses": address_list,
        "has_addresses": _bool(g(raw, "addresses", "is_enabled")),
        "main_address": card.get("address"),
        "counters": _counters(raw.get("counters")),
        "wiki_page": text(raw.get("wiki_page")),
        "has_market": _bool(g(raw, "market", "enabled")),
        "ban": {"reason": text(ban.get("comment")), "until": epoch_to_iso(ban.get("end_date"))} if ban else None,
    }


# ---- attachments ------------------------------------------------------------------------------

def _photo_record(raw):
    raw = as_dict(raw)
    owner_id, photo_id = to_int(raw.get("owner_id")), to_int(raw.get("id"))
    sizes = image_sizes(raw.get("sizes"))
    largest = sizes[-1] if sizes else {}
    post_id = to_int(raw.get("post_id"))
    return {
        "id": photo_id,
        "owner_id": owner_id,
        "link": refs.photo_link(owner_id, photo_id),
        "album_id": to_int(raw.get("album_id")),
        "text": text(raw.get("text")),
        "date": epoch_to_iso(raw.get("date")),
        "image": largest.get("link"),
        "width": largest.get("width"),
        "height": largest.get("height"),
        "images": sizes,
        "post_id": post_id,
        "post_link": refs.post_link(owner_id, post_id) if post_id else None,
        "uploader_id": to_int(raw.get("user_id")) if to_int(raw.get("user_id")) not in (None, 100) else None,
        "stats": {
            "likes": _count(raw.get("likes")),
            "comments": _count(raw.get("comments")),
            "reposts": _count(raw.get("reposts")),
            "tags": _count(raw.get("tags")),
        },
        "can_comment": _bool(raw.get("can_comment")),
    }


def parse_photo(raw):
    """photos.get / photos.getAll item -> the photo record."""
    return _photo_record(raw)


def _video_files(files):
    """VK's `files` {mp4_720: url, hls: url, dash_sep: url, …} -> the mp4
    renditions (best first) and the streaming manifests."""
    files = as_dict(files)
    downloads = []
    streams = {}
    for key, value in files.items():
        link = _link(value)
        if not link:
            continue
        match = re.fullmatch(r"(mp4|webm)_(\d+)", key)
        if match:
            downloads.append({"quality": int(match.group(2)), "format": match.group(1), "link": link})
        elif key != "failover_host":
            streams[key] = link
    downloads.sort(key=lambda d: d["quality"], reverse=True)
    return downloads, (streams or None)


def _subtitles(items):
    out = []
    for item in as_list(items):
        item = as_dict(item)
        out.append({"language": text(item.get("lang")), "title": text(item.get("title")),
                    "is_auto": _bool(item.get("is_auto")), "link": _link(item.get("url"))})
    return out


def _episodes(items):
    out = []
    for item in as_list(items):
        item = as_dict(item)
        out.append({"time": to_int(item.get("time")), "text": text(item.get("text"))})
    return out


def parse_video(raw, index=None):
    """video.get / shortVideo / catalog video item -> the video record. Clips
    (VK's short_video) share the shape; `kind` tells them apart."""
    raw = as_dict(raw)
    owner_id, video_id = to_int(raw.get("owner_id")), to_int(raw.get("id"))
    kind = {"short_video": "clip", "live": "live", "music_video": "music_video"}.get(text(raw.get("type")) or "", "video")
    if g(raw, "live_status") in ("started", "waiting", "upcoming"):
        kind = "live"
    downloads, streams = _video_files(raw.get("files"))
    download = as_dict(raw.get("download"))
    action = as_dict(raw.get("action_button"))
    post_id = to_int(raw.get("wall_post_id"))
    thumbnails = image_sizes(raw.get("image"))
    first_frames = image_sizes(raw.get("first_frame"))
    return {
        "id": video_id,
        "owner_id": owner_id,
        "link": refs.video_link(owner_id, video_id, is_clip=(kind == "clip")),
        "vkvideo_link": _link(raw.get("direct_url")),
        "kind": kind,
        "title": text(raw.get("title")),
        "description": html_to_text(raw.get("description")),
        "author": author_card(owner_id, index or {}),
        "date": epoch_to_iso(raw.get("date")),
        "added_date": epoch_to_iso(raw.get("adding_date")),
        "duration_seconds": to_int(raw.get("duration")),
        "width": to_int(raw.get("width")),
        "height": to_int(raw.get("height")),
        "thumbnail": thumbnails[-1]["link"] if thumbnails else None,
        "thumbnails": thumbnails,
        "first_frame": first_frames[-1]["link"] if first_frames else None,
        "stats": {
            "views": to_int(raw.get("views")),
            "likes": _count(raw.get("likes")),
            "comments": _count(raw.get("comments")),
            "reposts": _count(raw.get("reposts")),
        },
        "is_pinned": _bool(raw.get("is_pinned")),
        "is_live": kind == "live",
        "live_status": text(raw.get("live_status")),
        "has_subtitles": _bool(raw.get("has_subtitles")) if "has_subtitles" in raw else (bool(raw.get("subtitles")) or None),
        "subtitles": _subtitles(raw.get("subtitles")),
        "chapters": _episodes(raw.get("episodes")),
        "downloads": downloads,
        "streams": streams,
        "trailer": _link(g(raw, "trailer", "mp4_1080")) or next((_link(v) for v in as_dict(raw.get("trailer")).values() if _link(v)), None),
        "is_downloadable": _bool(download.get("can_download_to_device")) if download else _bool(raw.get("can_download")),
        "player_link": _link(raw.get("player")),
        "post_id": post_id,
        "post_link": refs.post_link(owner_id, post_id) if post_id else None,
        "action_button": {
            "type": text(action.get("type")),
            "title": text(g(action, "snippet", "open_title")) or text(g(action, "snippet", "title")),
            "link": _link(action.get("url")),
        } if action and _link(action.get("url")) else None,
        "loops": _bool(raw.get("repeat")) if "repeat" in raw else None,
    }


def _link_attachment(raw):
    raw = as_dict(raw)
    return {
        "type": "link",
        "link": _link(raw.get("url")),
        "title": text(raw.get("title")),
        "caption": text(raw.get("caption")),
        "description": text(raw.get("description")),
        "image": largest_image(g(raw, "photo", "sizes")),
        "button": text(g(raw, "button", "title")),
    }


def _doc_attachment(raw):
    raw = as_dict(raw)
    owner_id, doc_id = to_int(raw.get("owner_id")), to_int(raw.get("id"))
    return {
        "type": "document",
        "id": doc_id,
        "owner_id": owner_id,
        "title": text(raw.get("title")),
        "extension": text(raw.get("ext")),
        "size_bytes": to_int(raw.get("size")),
        "date": epoch_to_iso(raw.get("date")),
        "link": _link(raw.get("url")),
        "preview": largest_image(g(raw, "preview", "photo", "sizes")),
    }


def _audio_attachment(raw):
    raw = as_dict(raw)
    owner_id, audio_id = to_int(raw.get("owner_id")), to_int(raw.get("id"))
    return {
        "type": "audio",
        "id": audio_id,
        "owner_id": owner_id,
        "artist": text(raw.get("artist")),
        "title": text(raw.get("title")),
        "duration_seconds": to_int(raw.get("duration")),
        "link": _link(raw.get("url")),
        "is_explicit": _bool(raw.get("is_explicit")),
    }


def _poll_attachment(raw):
    raw = as_dict(raw)
    answers = []
    for answer in as_list(raw.get("answers")):
        answer = as_dict(answer)
        answers.append({"id": to_int(answer.get("id")), "text": text(answer.get("text")),
                        "votes": to_int(answer.get("votes")), "rate_pct": answer.get("rate")})
    return {
        "type": "poll",
        "id": to_int(raw.get("id")),
        "owner_id": to_int(raw.get("owner_id")),
        "question": text(raw.get("question")),
        "votes": to_int(raw.get("votes")),
        "answers": answers,
        "is_anonymous": _bool(raw.get("anonymous")),
        "is_multiple": _bool(raw.get("multiple")),
        "is_closed": _bool(raw.get("closed")),
        "created": epoch_to_iso(raw.get("created")),
        "ends": epoch_to_iso(raw.get("end_date")),
    }


def parse_article_card(raw):
    """articles.getOwnerPublished item / article attachment -> the article card."""
    raw = as_dict(raw)
    owner_id, article_id = to_int(raw.get("owner_id")), to_int(raw.get("id"))
    link = _link(raw.get("url"))
    return {
        "id": article_id,
        "owner_id": owner_id,
        "title": text(raw.get("title")),
        "subtitle": text(raw.get("subtitle")),
        "link": link,
        "slug": link.rsplit("/@", 1)[-1] if link and "/@" in link else None,
        "author": {"id": owner_id, "name": text(raw.get("owner_name")), "link": refs.owner_link(owner_id),
                   "photo": _link(raw.get("owner_photo"))},
        "published": epoch_to_iso(raw.get("published_date")),
        "lead": html_to_text(raw.get("lead_description")),
        "image": largest_image(g(raw, "photo", "sizes")),
        "stats": {"views": to_int(raw.get("views")), "shares": to_int(raw.get("shares"))},
        "reading_time_seconds": to_int(raw.get("time_to_read")),
        "is_pinned": _bool(raw.get("is_pinned")),
        "state": text(raw.get("state")),
    }


def _sticker_attachment(raw):
    raw = as_dict(raw)
    return {
        "type": "sticker",
        "id": to_int(raw.get("sticker_id")),
        "product_id": to_int(raw.get("product_id")),
        "image": largest_image(raw.get("images")),
        "animation": _link(raw.get("animation_url")),
    }


def _market_attachment(raw):
    raw = as_dict(raw)
    price = as_dict(raw.get("price"))
    owner_id, item_id = to_int(raw.get("owner_id")), to_int(raw.get("id"))
    return {
        "type": "product",
        "id": item_id,
        "owner_id": owner_id,
        "link": f"{refs.SITE}/market{owner_id}?w=product{owner_id}_{item_id}" if owner_id is not None and item_id is not None else None,
        "title": text(raw.get("title")),
        "description": text(raw.get("description")),
        "price": to_int(price.get("amount")) / 100 if to_int(price.get("amount")) is not None else None,
        "currency": text(g(price, "currency", "name")),
        "price_text": text(price.get("text")),
        "image": _link(raw.get("thumb_photo")),
        "availability": to_int(raw.get("availability")),
    }


def _generic_attachment(kind, raw):
    raw = as_dict(raw)
    owner_id, item_id = to_int(raw.get("owner_id")), to_int(raw.get("id"))
    return {
        "type": kind,
        "id": item_id,
        "owner_id": owner_id,
        "title": text(raw.get("title")) or text(raw.get("name")) or text(raw.get("text")),
        "link": _link(raw.get("url")) or _link(raw.get("view_url")),
        "image": largest_image(raw.get("sizes")) or _link(raw.get("thumb")) or _link(raw.get("photo_200")),
    }


def parse_attachment(raw):
    raw = as_dict(raw)
    kind = text(raw.get("type"))
    body = raw.get(kind) if kind else None
    if not kind:
        return None
    if kind == "photo":
        return {"type": "photo", **_photo_record(body)}
    if kind == "video":
        return {"type": "video", **parse_video(body)}
    if kind == "link":
        return _link_attachment(body)
    if kind == "doc":
        return _doc_attachment(body)
    if kind == "audio":
        return _audio_attachment(body)
    if kind == "poll":
        return _poll_attachment(body)
    if kind == "article":
        return {"type": "article", **parse_article_card(body)}
    if kind == "sticker":
        return _sticker_attachment(body)
    if kind == "market":
        return _market_attachment(body)
    return _generic_attachment(kind, body)


def parse_attachments(items):
    out = []
    for item in as_list(items):
        parsed = parse_attachment(item)
        if parsed:
            out.append(parsed)
    return out


# ---- posts ------------------------------------------------------------------------------------

def reaction_titles(response):
    """{reaction id: title} from the `reaction_sets` of a wall response."""
    titles = {}
    for reaction_set in as_list(g(response, "reaction_sets")):
        for item in as_list(g(reaction_set, "items")):
            rid, title = to_int(g(item, "id")), text(g(item, "title"))
            if rid is not None and title:
                titles[rid] = title
    return titles


def _reactions(raw, titles):
    items = []
    for item in as_list(g(raw, "items")):
        rid = to_int(g(item, "id"))
        items.append({"id": rid, "name": (titles or {}).get(rid), "count": to_int(g(item, "count"))})
    return {"total": to_int(g(raw, "count")), "items": items} if isinstance(raw, dict) else None


def _geo(raw):
    raw = as_dict(raw)
    if not raw:
        return None
    place = as_dict(raw.get("place"))
    coordinates = text(raw.get("coordinates"))
    lat = lon = None
    if coordinates:
        parts = coordinates.split()
        if len(parts) == 2:
            try:
                lat, lon = float(parts[0]), float(parts[1])
            except ValueError:
                lat = lon = None
    return {
        "type": text(raw.get("type")),
        "latitude": lat if lat is not None else place.get("latitude"),
        "longitude": lon if lon is not None else place.get("longitude"),
        "place": {"id": to_int(place.get("id")), "title": text(place.get("title")),
                  "address": text(place.get("address")), "city": text(place.get("city")),
                  "country": text(place.get("country"))} if place else None,
    }


def parse_post(raw, index=None, titles=None, depth=0):
    """A wall post (wall.get / wall.getById / wall.search item) -> the post
    record. `index` is people_index() of the response (author cards),
    `titles` reaction_titles() of it. Reposts carry the original post(s)
    under `repost_of` (VK's copy_history)."""
    raw = as_dict(raw)
    index = index or {}
    owner_id, post_id = to_int(raw.get("owner_id")), to_int(raw.get("id"))
    source = as_dict(raw.get("post_source"))
    copyright_ = as_dict(raw.get("copyright"))
    signer_id = to_int(raw.get("signer_id"))
    comments = as_dict(raw.get("comments"))
    return {
        "id": post_id,
        "owner_id": owner_id,
        "link": refs.post_link(owner_id, post_id),
        "author": author_card(raw.get("from_id"), index),
        "text": text(raw.get("text")) if raw.get("text") is None else (html_lib.unescape(str(raw.get("text"))).strip() or None),
        "date": epoch_to_iso(raw.get("date")),
        "edited": epoch_to_iso(raw.get("edited")),
        "type": text(raw.get("post_type")) or text(raw.get("type")),
        "is_pinned": _bool(raw.get("is_pinned")) or False,
        "is_ad": _bool(raw.get("marked_as_ads")) or False,
        "is_deleted": _bool(raw.get("is_deleted")) or False,
        "deleted_reason": text(raw.get("deleted_reason")),
        "stats": {
            "likes": _count(raw.get("likes")),
            "reactions": _reactions(raw.get("reactions"), titles),
            "comments": to_int(comments.get("count")),
            "reposts": _count(raw.get("reposts")),
            "views": _count(raw.get("views")),
        },
        "comments_enabled": _bool(comments.get("can_post")) if comments else None,
        "comments_visible": _bool(comments.get("can_view")) if comments else None,
        "attachments": parse_attachments(raw.get("attachments")),
        "repost_of": [parse_post(cp, index, titles, depth + 1) for cp in as_list(raw.get("copy_history"))] if depth < 3 else [],
        "signer": author_card(signer_id, index) if signer_id else None,
        "geo": _geo(raw.get("geo")),
        "copyright": {"link": _link(copyright_.get("link")), "name": text(copyright_.get("name")),
                      "type": text(copyright_.get("type"))} if copyright_ else None,
        "source": {"type": text(source.get("type")), "platform": text(source.get("platform")),
                   "data": text(source.get("data")), "link": _link(source.get("url"))} if source else None,
        "is_donut": _bool(g(raw, "donut", "is_donut")),
    }


def parse_wall(response):
    """wall.get / wall.search response -> (posts, total_count)."""
    response = as_dict(response)
    index = people_index(response)
    titles = reaction_titles(response)
    posts = [parse_post(item, index, titles) for item in as_list(response.get("items"))]
    return posts, to_int(response.get("count"))


def parse_wall_search(response):
    """wall.search response -> (posts, items VK returned). On a user's wall
    VK also returns visitors' comments that match (post_type "reply"); they
    are not posts and are dropped. VK's `count` here is the size of the
    returned page, not a total, so the raw item count is what tells whether
    another page exists."""
    response = as_dict(response)
    items = as_list(response.get("items"))
    index = people_index(response)
    titles = reaction_titles(response)
    posts = [parse_post(item, index, titles) for item in items
             if not (isinstance(item, dict) and item.get("post_type") == "reply")]
    return posts, len(items)


def parse_post_by_id(response):
    """wall.getById response -> the post record or None (no such post). A
    deleted post comes back as a stub with is_deleted = true."""
    response = as_dict(response)
    items = as_list(response.get("items"))
    if not items:
        return None
    return parse_post(items[0], people_index(response), reaction_titles(response))


# ---- comments ---------------------------------------------------------------------------------

def parse_comment(raw, index=None, post_owner_id=None, post_id=None):
    raw = as_dict(raw)
    index = index or {}
    owner_id = to_int(raw.get("owner_id")) if raw.get("owner_id") is not None else post_owner_id
    post_id = to_int(raw.get("post_id")) if raw.get("post_id") is not None else post_id
    comment_id = to_int(raw.get("id"))
    thread = as_dict(raw.get("thread"))
    reply_user, reply_comment = to_int(raw.get("reply_to_user")), to_int(raw.get("reply_to_comment"))
    return {
        "id": comment_id,
        "post_id": post_id,
        "owner_id": owner_id,
        "link": refs.comment_link(owner_id, post_id, comment_id),
        "author": author_card(raw.get("from_id"), index),
        "text": html_lib.unescape(str(raw.get("text"))).strip() or None if raw.get("text") is not None else None,
        "date": epoch_to_iso(raw.get("date")),
        "likes": _count(raw.get("likes")),
        "attachments": parse_attachments(raw.get("attachments")),
        "reply_to": {"user_id": reply_user, "comment_id": reply_comment,
                     "user": author_card(reply_user, index) if reply_user else None} if reply_user or reply_comment else None,
        "parent_ids": [to_int(p) for p in as_list(raw.get("parents_stack")) if to_int(p) is not None],
        "is_from_post_author": _bool(raw.get("is_from_post_author")) or False,
        "is_deleted": _bool(raw.get("deleted")) or False,
        "replies": {
            "count": to_int(thread.get("count")),
            "items": [parse_comment(item, index, owner_id, post_id) for item in as_list(thread.get("items"))],
        } if thread else None,
    }


def parse_comments(response, post_owner_id=None, post_id=None):
    """wall.getComments / video.getComments response -> (comments, total
    top-level count, total count including replies)."""
    response = as_dict(response)
    index = people_index(response)
    comments = [parse_comment(item, index, post_owner_id, post_id) for item in as_list(response.get("items"))]
    return comments, to_int(response.get("current_level_count")), to_int(response.get("count"))


# ---- lists --------------------------------------------------------------------------------------

def parse_cards(response):
    """users.getFollowers / groups.getMembers response -> (cards, total)."""
    response = as_dict(response)
    cards = [profile_card(item) for item in as_list(response.get("items")) if isinstance(item, dict)]
    return cards, to_int(response.get("count"))


def parse_videos(response):
    """video.get response -> (videos, total)."""
    response = as_dict(response)
    index = people_index(response)
    return [parse_video(item, index) for item in as_list(response.get("items"))], to_int(response.get("count"))


def parse_video_by_id(response):
    """video.get(videos=…) response -> the record or None. An id that does
    not exist answers a stub without a title / files / date."""
    videos, _ = parse_videos(response)
    if not videos:
        return None
    video = videos[0]
    if not video["title"] and not video["date"] and not video["downloads"] and not video["thumbnail"]:
        return None
    return video


def parse_clips(response):
    """shortVideo.getOwnerVideos response -> (clips, total, next_from)."""
    response = as_dict(response)
    index = people_index(response)
    clips = [parse_video(item, index) for item in as_list(response.get("items"))]
    return clips, to_int(response.get("count")), text(response.get("next_from"))


def parse_photos(response):
    response = as_dict(response)
    return [parse_photo(item) for item in as_list(response.get("items"))], to_int(response.get("count"))


def parse_articles(response):
    response = as_dict(response)
    return [parse_article_card(item) for item in as_list(response.get("items"))], to_int(response.get("count"))


# ---- catalog search -------------------------------------------------------------------------------

def _section(response):
    """The section of a catalog.get* (first section) or catalog.getSection
    (`section`) response."""
    response = as_dict(response)
    if isinstance(response.get("section"), dict):
        return response["section"]
    return as_dict(g(response, "catalog", "sections", 0))


def parse_community_search(response):
    """catalog.getSearchGroups / catalog.getSection response ->
    (community cards, section id, next_from)."""
    response = as_dict(response)
    section = _section(response)
    cards = [community_card(item) for item in as_list(response.get("groups"))]
    return cards, text(section.get("id")), text(section.get("next_from"))


def parse_playlist(raw):
    raw = as_dict(raw)
    owner_id, album_id = to_int(raw.get("owner_id")), to_int(raw.get("id"))
    return {
        "id": album_id,
        "owner_id": owner_id,
        "title": text(raw.get("title")),
        "link": f"{refs.VIDEO_SITE}/playlist/{owner_id}_{album_id}" if owner_id is not None and album_id is not None else None,
        "videos_count": to_int(raw.get("count")),
        "followers_count": to_int(raw.get("followers_count")),
        "updated": epoch_to_iso(raw.get("updated_time")),
        "image": largest_image(raw.get("image")),
        "first_video_link": _link(raw.get("first_video_url")),
    }


def parse_video_search(response):
    """catalog.getVideoSearch / catalog.getSection response ->
    (videos in page order, playlists, section id, next_from). The catalog
    lays the page out as blocks: "New videos by creator" (`videos`), "All
    videos" (`catalog_videos`) and "Playlists" (`albums`); the ids in each
    block give the order, the entity lists give the records."""
    response = as_dict(response)
    index = people_index(response)
    section = _section(response)
    by_id = {}
    for raw in as_list(response.get("videos")):
        video = parse_video(raw, index)
        by_id[f"{video['owner_id']}_{video['id']}"] = video
    for wrapper in as_list(response.get("catalog_videos")):
        video = parse_video(g(wrapper, "video"), index)
        by_id.setdefault(f"{video['owner_id']}_{video['id']}", video)
    ordered, seen = [], set()
    for block in as_list(section.get("blocks")):
        for vid in as_list(g(block, "videos_ids")):
            key = text(vid)
            if key in by_id and key not in seen:
                ordered.append(by_id[key])
                seen.add(key)
    for key, video in by_id.items():
        if key not in seen:
            ordered.append(video)
            seen.add(key)
    playlists = [parse_playlist(raw) for raw in as_list(response.get("albums"))]
    return ordered, playlists, text(section.get("id")), text(section.get("next_from"))


# ---- the article page -----------------------------------------------------------------------------

_LD_JSON_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_META_RE = r'<meta property="{name}" content="([^"]*)"'
_ARTICLE_ID_RE = re.compile(r'id="article_view_(-?\d+)_(\d+)"')
_ARTICLE_START_RE = re.compile(r'<div class="article article_view[^>]*>')
_ARTICLE_END_MARKERS = ('class="article_layer_misc', 'class="article_layer__simple_footer',
                        'class="article_layer_ads_place', 'class="article_layer__footer')
_ANCHOR_RE = re.compile(r"<span class='article_anchor_button'.*?</span>", re.S)
_TAG_TEXT_RE = re.compile(r"<(h1|h2|h3)[^>]*>(.*?)</\1>", re.S)
_IMG_RE = re.compile(r"<img[^>]+(?:data-src|src)=\"([^\"]+)\"", re.I)
_LINK_RE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)


def _meta(html, name):
    match = re.search(_META_RE.format(name=re.escape(name)), html)
    return html_lib.unescape(match.group(1)).strip() if match else None


def _ld_json(html):
    match = _LD_JSON_RE.search(html)
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _iso_from_offset(value):
    """'2023-09-28T13:37:37+03:00' -> '2023-09-28T10:37:37Z'."""
    value = text(value)
    if not value:
        return None
    from datetime import datetime, timezone
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_article_page(html, slug):
    """The server-rendered vk.ru/@<slug> page -> the article record: the
    schema.org header (title, dates, author), the og image, and the body as
    plain text plus its headings, images and outbound links."""
    html = html or ""
    ld = _ld_json(html)
    ids = _ARTICLE_ID_RE.search(html)
    owner_id = to_int(ids.group(1)) if ids else None
    article_id = to_int(ids.group(2)) if ids else None
    start = _ARTICLE_START_RE.search(html)
    body_html = ""
    if start:
        rest = html[start.end():]
        end = min([i for i in (rest.find(m) for m in _ARTICLE_END_MARKERS) if i > 0] or [len(rest)])
        body_html = rest[:end]
    body_html = _ANCHOR_RE.sub("", body_html)
    body_html = re.sub(r"<svg.*?</svg>", "", body_html, flags=re.S)
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", body_html, re.S)
    title = text(re.sub(r"<[^>]+>", " ", title_match.group(1))) if title_match else None
    headings = []
    for tag, inner in _TAG_TEXT_RE.findall(body_html):
        if tag == "h1":
            continue
        heading = text(re.sub(r"<[^>]+>", " ", inner))
        if heading:
            headings.append({"level": int(tag[1]), "text": heading})
    images = []
    for src in _IMG_RE.findall(body_html):
        link = _link(html_lib.unescape(src))
        if link and link not in images:
            images.append(link)
    links = []
    for href, inner in _LINK_RE.findall(body_html):
        href = html_lib.unescape(href)
        if "/away.php" in href:
            # VK's outbound redirector wraps every external link
            match = re.search(r"[?&]to=([^&]+)", href)
            if match:
                from urllib.parse import unquote
                href = unquote(match.group(1))
        link = _link(href)
        label = text(re.sub(r"<[^>]+>", " ", inner))
        if link and (link, label) not in [(l["link"], l["text"]) for l in links]:
            links.append({"link": link, "text": label})
    body_text = html_to_text(re.sub(r"<h1[^>]*>.*?</h1>", "", body_html, count=1, flags=re.S))
    author = as_dict(ld.get("author"))
    # the layer footer is "<n> views" in the exit's language; only the digits are read
    views_match = re.search(r'article_layer__simple_footer">\s*([\d][\d\s,.\xa0]*)', html)
    views = to_int(re.sub(r"[^\d]", "", views_match.group(1))) if views_match else None
    return {
        "id": article_id,
        "owner_id": owner_id,
        "slug": slug,
        "link": refs.article_link(slug),
        "title": title or text(ld.get("headline")) or _meta(html, "og:title"),
        "subtitle": text(ld.get("description")) or _meta(html, "og:description"),
        "author": {
            "id": owner_id,
            "name": text(author.get("name")),
            "type": "community" if (owner_id or 0) < 0 else ("user" if owner_id else None),
            "link": refs.owner_link(owner_id) if owner_id else None,
        },
        "published": _iso_from_offset(ld.get("datePublished")),
        "modified": _iso_from_offset(ld.get("dateModified")),
        "image": _link(_meta(html, "og:image")),
        "views": views,
        "text": body_text,
        "headings": headings,
        "images": images,
        "links": links,
        "word_count": len(body_text.split()) if body_text else 0,
    }
