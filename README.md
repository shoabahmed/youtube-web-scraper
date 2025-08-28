## YouTube Hashtag Scraper (Selenium)

Scrape videos from a YouTube hashtag page using Selenium, and export results to CSV.

### Requirements
- Python 3.9+
- Google Chrome installed (the script auto-installs a matching ChromeDriver via webdriver-manager)

### Install
```powershell
cd C:\Users\shoab\Desktop\repo
python -m venv .venv
. .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Usage
```powershell
# Example: scrape #python videos headless with 10 scrolls
python .\scrape_youtube_hashtag.py "#python" --headless --scrolls 10 --hl en --geo US --out python.csv

# Minimal
python .\scrape_youtube_hashtag.py "#python"
```

- Extracted fields: title, video_id, url, channel_name, published_text, views_text, duration_text.
- Headless mode can be toggled with `--headless`.
- Increase `--scrolls` to load more results.

### Notes
- YouTube UI may change; if parsing fails, adjust logic in `parse_videos`.
- Respect YouTube’s Terms. Avoid high request rates. Consider official APIs for production.
# youtube-web-scraper
