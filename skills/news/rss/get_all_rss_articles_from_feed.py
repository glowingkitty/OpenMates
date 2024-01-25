import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json
import re
import os
import sys
import traceback
from slugify import slugify

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
from skills.intelligence.count_tokens import count_tokens


def get_all_rss_articles_from_feed(
        feed_url: str,
        use_existing_file_if_exists: bool = False,
        save_as_json: bool = False,
        within_last_x_days: int = 1,
        mark_all_as_do_not_filter_out: bool = False
        ) -> list:
    try:
        add_to_log(module_name="News | RSS | Get all articles from feed", color="cyan", state="start")
        
        add_to_log(f"Start getting news from rss feed '{feed_url}'...")

        current_date = datetime.now().strftime("%Y_%m_%d")
        folder_path = f"{main_directory}/temp_data/rss/{current_date}"
        feed_name_slugified = slugify(feed_url)
        json_filename = f"{folder_path}/news_{feed_name_slugified}.json"
        os.makedirs(folder_path, exist_ok=True)

        # check if the file exists, if so, load it and return it
        if use_existing_file_if_exists and os.path.exists(json_filename):
            add_to_log(f"\U00002714 Using existing file: news_{feed_name_slugified}.json")
            with open(json_filename, 'r') as f:
                return json.load(f)

        feed = feedparser.parse(feed_url)
        articles = []
        current_time = datetime.now()
        for entry in feed.entries:
            try:
                if hasattr(entry, 'published_parsed'):
                    entry_date = datetime(*entry.published_parsed[:6])
                elif hasattr(entry, 'updated_parsed'):
                    entry_date = datetime(*entry.updated_parsed[:6])
                else:
                    entry_date = None
                
                if entry_date:
                    entry_date_unix = int(entry_date.timestamp())

                    if current_time - entry_date <= timedelta(days=within_last_x_days):
                        description_html = entry.description
                        # clean up the description_html by removing unneeded long spaces
                        description_html = re.sub(r'\s+', ' ', description_html)
                        description_text = BeautifulSoup(description_html, features="html.parser").get_text()

                        # shorten the description text to 300 characters, and add "..." to the end if it was shortened
                        if len(description_text) > 300:
                            description_text_shortened = description_text[:300] + "..."
                        else:
                            description_text_shortened = description_text

                        # create an article ID, based on the first 50 characters of the entry link, but without the http(s):// and without the www. (so starting after that)
                        article_id = re.sub(r'https?://(www\.)?', '', entry.link)[:50]
                            
                        articles.append({
                            "title": entry.title,
                            "id":article_id,
                            "tags": [x["term"] for x in entry.tags] if hasattr(entry, 'tags') else [],
                            "article_date": entry_date.strftime("%Y-%m-%d %H:%M"),
                            "article_date_unix": entry_date_unix,
                            "description_text": description_text_shortened,
                            "text_for_highlights_filtering":f"{article_id} - {entry.title}: {description_text_shortened}",
                            "tokens_text_for_highlights_filtering":count_tokens(message=f"{article_id} - {entry.title}: {description_text_shortened}"),
                            "link": entry.link,
                            "do_not_filter_out": mark_all_as_do_not_filter_out
                            })
                    
                if save_as_json:
                    with open(json_filename, "w") as f:
                        json.dump(articles, f, indent=4)

            except Exception as e:
                add_to_log(state="error", message=f"Couldn't process an article.\n\nArticle: {entry}\n\nError: {e}\n\n")
                continue
        
        add_to_log(
            state="success",
            message="Successfully got news from rss feed '{feed_url}'")

        return articles
    

    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed getting news from rss feed", traceback=traceback.format_exc())



if __name__ == "__main__":
    articles = get_all_rss_articles_from_feed("https://www.wired.com/feed/rss", save_as_json=True)