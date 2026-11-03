"""Use the scraper straight from Python — no server needed.

    python main.py

Every call is validated by the same schema the API uses and returns the same
records; results are written to output/*.json.
"""
import json
import os

from schema_fields import load_query
from vk import api, schemas

os.makedirs("output", exist_ok=True)


def run(schema_cls, fn, **params):
    data, error = load_query(schema_cls, {k: str(v) for k, v in params.items()})
    if error:
        raise ValueError(error)
    return fn(**data)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a screen name, numeric ID or any vk.com profile link
    save("user_durov.json", run(schemas.UserSchema, api.users_details, user="durov"))

    # 20 wall posts per page with attachments, reactions, comments and views
    save("community_posts_spacex.json", run(schemas.CommunityPostsSchema, api.communities_posts, community="spacex"))

    # VK Video search with direct MP4 links
    save("videos_search_iphone_17.json", run(schemas.VideosSearchSchema, api.videos_search, query="iPhone 17 review"))
