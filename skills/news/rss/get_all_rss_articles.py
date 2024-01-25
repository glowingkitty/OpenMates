################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from skills.news.rss.get_all_rss_articles_from_feed import get_all_rss_articles_from_feed
from skills.intelligence.get_costs_chat import get_costs_chat

import json
from datetime import datetime


def get_all_rss_articles(
        use_existing_file_if_exists: bool = False,
        within_last_x_days: int = 2):
    try:
        add_to_log(module_name="News | RSS | Get all articles", color="cyan", state="start")

        add_to_log("Start getting all news ...")
        
        current_date = datetime.now().strftime("%Y_%m_%d")
        folder_path = f"{main_directory}/temp_data/rss/{current_date}"
        
        
        os.makedirs(folder_path, exist_ok=True)

        profile_details = load_profile_details()
        rss_feed_categories = profile_details["rss_feeds"]

        all_news = {}
        report = {}

        # add search unicode
        add_to_log("\U0001F50D Start searching for RSS feed news ...")
        # for every key in the rss_feed_categories dict
        for category in rss_feed_categories:
            json_filename = f"{folder_path}/news_{category}_{current_date}.json"

            # check if the file exists, if so, skip this category
            if use_existing_file_if_exists and os.path.exists(json_filename):
                add_to_log(f"\U00002714 Using existing file: news_{category}_{current_date}.json")
                with open(json_filename, 'r') as f:
                    report[category] = json.load(f)
                continue

            all_news[category] = []
            for rss_feed in rss_feed_categories[category]:
                articles = get_all_rss_articles_from_feed(
                    feed_url=rss_feed["feed_url"],
                    use_existing_file_if_exists=use_existing_file_if_exists,
                    save_as_json=True,
                    within_last_x_days=within_last_x_days,
                    mark_all_as_do_not_filter_out=rss_feed["always_include_all"] if "always_include_all" in rss_feed else False
                    )
                add_to_log(f"Found {len(articles)} articles in '{rss_feed['feed_url']}'")
                for article in articles:
                    news_item = {
                        "title": article['title'],
                        "link": article['link'],
                        "description": ', '.join(article['tags']) if article['tags'] and len(article['tags'])>2 else article['description_text'],
                        "text_for_highlights_filtering":article["text_for_highlights_filtering"],
                        "tokens_text_for_highlights_filtering":article["tokens_text_for_highlights_filtering"],
                        "do_not_filter_out": article["do_not_filter_out"]
                    }
                    all_news[category].append(news_item)

            # check pricing for text_for_highlights_filtering
            total_token_count = 0
            for item in all_news[category]:
                total_token_count += item["tokens_text_for_highlights_filtering"]

            # Calculate the tokens and costs for the articles
            token_costs_gpt_3_5 = get_costs_chat(num_input_tokens=total_token_count, model_name="gpt-3.5")

            report[category] = {
                "articles_num": len(all_news[category]),
                "tokens_for_highlights_filtering": total_token_count,
                "token_costs_gpt_3_5": round(token_costs_gpt_3_5["total_costs_min"],5) if token_costs_gpt_3_5 != 0 else 0,
                "articles": all_news[category]
            }

            with open(json_filename, "w") as f:
                json.dump(report[category], f, indent=4)


        total_tokens = 0
        total_token_costs_gpt_3_5 = 0

        for cat_report in report.values():
            total_tokens += cat_report["tokens_for_highlights_filtering"] if "tokens_for_highlights_filtering" in cat_report else 0
            total_token_costs_gpt_3_5 += cat_report["token_costs_gpt_3_5"] if "token_costs_gpt_3_5" in cat_report else 0

        report["total"] = {
            "articles": sum(cat_report["articles_num"] for cat_report in report.values()),
            "tokens": total_tokens,
            "token_costs_gpt_3_5": round(total_token_costs_gpt_3_5,3),
        }

        # Print the report
        add_to_log(f"Report: {report['total']}")

        return report
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to get all news", traceback=traceback.format_exc())
        return None

# Test the function
if __name__ == "__main__":
    all_news = get_all_rss_articles(use_existing_file_if_exists=True)