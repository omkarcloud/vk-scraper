# 👥 VK Scraper

VK Scraper is a **free and open-source** scraper that gets you **unlimited** detailed VK data for free.

## ✨ What Can I Get?

- 👤 **Full profiles of 90M+ monthly VK users** — name, status, followers, city, birthday, career, education & interests
- 📰 **Every wall post and comment, 20 per page** — text, photos, videos, reactions, reposts, views & reply threads
- 👥 **Communities with 14M+ members** — description, members, contacts, links, addresses, articles & photos
- 🎬 **VK Video, Russia's #1 video platform** — search videos & clips, get every MP4 rendition up to 4K, views & comments

## 🎥 Example: A Full VK Profile

```json
{
  "id": 1,
  "name": "Pavel Durov",
  "screen_name": "durov",
  "link": "https://vk.com/durov",
  "is_verified": true,
  "status": "道德經",
  "site": "http://t.me/durov",
  "birth_date": "1984-10-10",
  "city": { "id": 2, "name": "Saint Petersburg" },
  "country": { "id": 1, "name": "Russia" },
  "followers_count": 4515585,
  "photo": { "large": "https://sun9-81.vkuserphoto.ru/s/v1/ig1/36o_rXYV8irRb3HevhJemHEWX0J-MqFQSBXuIL9eVSUxNnbbsmmtQLxbNDJO6018NVaaMmfH.jpg?quality=96&crop=514,119,337,337&blur=5,10&as=32x32,48x48,72x72,108x108,160x160,240x240&ava=1&u=uOFKBVit3fNWiRE5u2E0F4zm_GiXN0pazp8LoszekMM&cs=200x200" },
  "occupation": { "type": "work", "name": "Telegram" },
  "career": [
    { "company": "Telegram", "position": "CEO", "from_year": 2014, "until_year": null }
  ],
  "universities": [{ "name": "СПбГУ", "graduation_year": 2006 }],
  "personal": {
    "political": "libertarian",
    "languages": ["Русский", "English", "Français", "Deutsch", "Español", "Italiano"],
    "inspired_by": "Steve Jobs",
    "people_main": "courage and persistence"
  },
  "interests": { "movies": "12 Angry Men" }
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free VK Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/vk-scraper
cd vk-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/users/details?user=durov"
```

```json
{
  "id": 1,
  "name": "Pavel Durov",
  "first_name": "Pavel",
  "last_name": "Durov",
  "screen_name": "durov",
  "link": "https://vk.com/durov",
  "is_verified": true,
  "is_closed": false,
  "status": "道德經",
  "site": "http://t.me/durov",
  "sex": "male",
  "birth_date": "1984-10-10",
  "city": { "id": 2, "name": "Saint Petersburg" },
  "country": { "id": 1, "name": "Russia" },
  "followers_count": 4515585,
  "occupation": { "type": "work", "name": "Telegram", "id": null }
}
```

All 22 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

22 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| User Details | `/users/details` | Full profile: status, followers, city, birthday, career, education, interests |
| User & Community Posts | `/users/posts` · `/communities/posts` | 20 wall posts per page with attachments, reactions and views |
| Search User & Community Posts | `/users/posts/search` · `/communities/posts/search` | Wall posts that mention your word or phrase |
| User Followers | `/users/followers` | 50 followers per page with name, photo and link |
| User & Community Videos | `/users/videos` · `/communities/videos` | Videos with views, likes, thumbnails and direct MP4 links |
| User & Community Clips | `/users/clips` · `/communities/clips` | Short videos with caption, views, likes and direct MP4 links |
| User & Community Photos | `/users/photos` · `/communities/photos` | 50 photos per page in every size, with likes |
| Search Communities | `/communities/search` | Communities by keyword with members, activity and address |
| Community Details | `/communities/details` | Description, members, status, website, contacts, links and addresses |
| Community Articles | `/communities/articles` | Published articles with views, shares and reading time |
| Community Members | `/communities/members` | Total member count plus an 8-member preview |
| Post Details | `/posts/details` | One post: full text, author, attachments, reactions and views |
| Post Comments | `/posts/comments` | 50 comments per page with likes and reply threads |
| Search Videos | `/videos/search` | VK Video results with views, duration and direct MP4 links |
| Video Details | `/videos/details` | Every MP4 rendition up to 4K, subtitles, views and likes |
| Video Comments | `/videos/comments` | 50 comments per page with likes and reply threads |
| Article Details | `/articles/details` | Full article text, headings, links, views and publish date |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-vk-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-vk-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-vk-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/communities/posts/search",
    params={"community": "spacex", "query": "Starship"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about VK Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/vk-scraper-github-whatsapp)

[![Ask Us by Email about VK Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](https://www.omkar.cloud/l/vk-scraper-github-email)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/vk-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/vk-scraper)
