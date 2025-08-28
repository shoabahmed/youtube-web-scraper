#!/usr/bin/env python3

import argparse
import csv
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager


YOUTUBE_BASE = "https://www.youtube.com"
HASHTAG_URL_TEMPLATE = YOUTUBE_BASE + "/hashtag/{tag}"


@dataclass
class VideoItem:
	title: str
	video_id: str
	url: str
	channel_name: Optional[str]
	published_text: Optional[str]
	views_text: Optional[str]
	duration_text: Optional[str]
	description_text: Optional[str] = None


def create_driver(headless: bool, lang: str) -> webdriver.Chrome:
	options = ChromeOptions()
	if headless:
		options.add_argument("--headless=new")
	options.add_argument("--disable-gpu")
	options.add_argument("--no-sandbox")
	options.add_argument("--disable-dev-shm-usage")
	options.add_argument(f"--lang={lang}")
	options.add_argument(
		"--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
		"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
	)
	service = ChromeService(ChromeDriverManager().install())
	driver = webdriver.Chrome(service=service, options=options)
	driver.set_page_load_timeout(60)
	return driver


def wait_for_page_ready(driver: webdriver.Chrome) -> None:
	WebDriverWait(driver, 30).until(
		lambda d: d.execute_script("return document.readyState") == "complete"
	)


def scroll_to_load(driver: webdriver.Chrome, max_scrolls: int, pause_ms: int = 1200) -> None:
	last_height = driver.execute_script("return document.documentElement.scrollHeight")
	for _ in range(max_scrolls):
		driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight);")
		WebDriverWait(driver, 30).until(lambda d: True)
		driver.implicitly_wait(0.1)
		driver.execute_script("return 0")
		driver.execute_script(f"return new Promise(r=>setTimeout(r,{pause_ms}))")
		now_height = driver.execute_script("return document.documentElement.scrollHeight")
		if now_height == last_height:
			break
		last_height = now_height


def try_accept_consent(driver: webdriver.Chrome) -> None:
	try:
		WebDriverWait(driver, 5).until(
			EC.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label*='Accept'], button[aria-label*='Agree']"))
		).click()
	except Exception:
		pass


def extract_initial_data_with_js(driver: webdriver.Chrome) -> Dict[str, Any]:
	data = driver.execute_script("return window.ytInitialData || null;")
	if not data:
		raise RuntimeError("ytInitialData not found on the page")
	return data


def _dig_video_renderers(obj: Any) -> Iterable[Dict[str, Any]]:
	if isinstance(obj, dict):
		if "videoRenderer" in obj and isinstance(obj["videoRenderer"], dict):
			yield obj["videoRenderer"]
		for value in obj.values():
			yield from _dig_video_renderers(value)
	elif isinstance(obj, list):
		for item in obj:
			yield from _dig_video_renderers(item)


def _text(runs: Optional[List[Dict[str, Any]]]) -> Optional[str]:
	if not runs:
		return None
	return "".join(part.get("text", "") for part in runs)


def parse_videos(initial_data: Dict[str, Any]) -> List[VideoItem]:
	items: List[VideoItem] = []
	for vr in _dig_video_renderers(initial_data):
		title = (
			vr.get("title", {}).get("runs", [{}])[0].get("text")
			or vr.get("title", {}).get("simpleText")
			or ""
		)
		video_id = vr.get("videoId", "")
		if not video_id:
			continue
		url = f"{YOUTUBE_BASE}/watch?v={video_id}"
		channel_name = _text(vr.get("ownerText", {}).get("runs"))
		published_text = (
			vr.get("publishedTimeText", {}).get("simpleText")
			or _text(vr.get("publishedTimeText", {}).get("runs"))
		)
		views_text = (
			vr.get("viewCountText", {}).get("simpleText")
			or _text(vr.get("viewCountText", {}).get("runs"))
			or _text(vr.get("shortViewCountText", {}).get("runs"))
		)
		duration_text = vr.get("lengthText", {}).get("simpleText")
		items.append(
			VideoItem(
				title=title,
				video_id=video_id,
				url=url,
				channel_name=channel_name,
				published_text=published_text,
				views_text=views_text,
				duration_text=duration_text,
			)
		)
	return items


def enrich_with_descriptions(driver: webdriver.Chrome, items: List[VideoItem], lang: str) -> None:
	orig = driver.current_window_handle
	for item in items:
		try:
			driver.execute_script("window.open(arguments[0], '_blank');", item.url)
			WebDriverWait(driver, 10).until(lambda d: len(d.window_handles) > 1)
			driver.switch_to.window(driver.window_handles[-1])
			wait_for_page_ready(driver)
			try_accept_consent(driver)
			# Try meta description first (single literal to avoid escape issues)
			desc = driver.execute_script("var m=document.querySelector(\"meta[name='description']\"); return m?m.getAttribute('content'):null;")
			if not desc:
				# Fallback to ytInitialPlayerResponse or ytInitialData browse content
				data = driver.execute_script("return window.ytInitialPlayerResponse || window.ytInitialData || null;")
				if data and isinstance(data, dict):
					try:
						# player microformat description
						desc = (
							data.get("microformat", {})
							.get("playerMicroformatRenderer", {})
							.get("description", {})
							.get("simpleText")
						)
					except Exception:
						desc = None
			item.description_text = desc
		except Exception:
			item.description_text = None
		finally:
			try:
				driver.close()
			except Exception:
				pass
			try:
				driver.switch_to.window(orig)
			except Exception:
				pass


def write_csv(items: List[VideoItem], output_path: str) -> None:
	fieldnames = list(asdict(VideoItem("", "", "", None, None, None, None)).keys())
	with open(output_path, "w", newline="", encoding="utf-8") as f:
		writer = csv.DictWriter(f, fieldnames=fieldnames)
		writer.writeheader()
		for item in items:
			writer.writerow(asdict(item))


def main(argv: Optional[List[str]] = None) -> int:
	parser = argparse.ArgumentParser(description="Scrape YouTube hashtag page to CSV using Selenium")
	parser.add_argument("hashtag", help="Hashtag to fetch, with or without leading #, e.g. #python")
	parser.add_argument("--out", default=None, help="Output CSV path (default: hashtag_YYYYmmdd_HHMMSS.csv)")
	parser.add_argument("--hl", default="en", help="UI language, e.g. en, hi, fr")
	parser.add_argument("--geo", default="US", help="Geolocation, e.g. US, IN, GB")
	parser.add_argument("--scrolls", type=int, default=8, help="How many times to scroll to load more")
	parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
	parser.add_argument("--include-description", action="store_true", help="Visit each video to capture description")
	args = parser.parse_args(argv)

	tag = args.hashtag.lstrip("#")
	url = HASHTAG_URL_TEMPLATE.format(tag=tag)

	driver = create_driver(headless=args.headless, lang=args.hl)
	try:
		driver.get(url)
		wait_for_page_ready(driver)
		try_accept_consent(driver)
		scroll_to_load(driver, max_scrolls=args.scrolls)
		initial_data = extract_initial_data_with_js(driver)
		items = parse_videos(initial_data)
		if args.include_description and items:
			enrich_with_descriptions(driver, items, lang=args.hl)
	finally:
		driver.quit()

	if not items:
		print("No videos found. YouTube may have changed its structure or content is restricted.", file=sys.stderr)

	out_path = args.out or f"{tag}_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
	write_csv(items, out_path)
	print(f"Saved {len(items)} videos to {out_path}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
