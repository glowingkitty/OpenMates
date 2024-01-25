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

from skills.news.rss.get_all_rss_articles import get_all_rss_articles
from skills.news.rss.get_article_full_text import get_article_full_text
from skills.news.get_systemprompt import get_systemprompt
from skills.intelligence.count_tokens import count_tokens
from skills.intelligence.ask_llm import ask_llm

import asyncio
import json
from datetime import datetime
from typing import Union


def get_rss_highlights(
        use_existing_file_if_exists: bool = False,
        add_full_content: bool = True, 
        save_as_json: bool = False,
        save_as_md: bool = False,
        return_content: str = "md") -> Union[dict, str]:

    try:
        add_to_log(module_name="News | RSS | Get highlights", state="start", color="cyan")

        add_to_log("Start getting news filtered for highlights ...")

        current_date = datetime.now().strftime("%Y_%m_%d")
        folder_path = f"{main_directory}/temp_data/rss/{current_date}"
        json_filename = f"{folder_path}/news_filtered_for_highlights_{current_date}.json"
        text_filename = f"{folder_path}/news_filtered_for_highlights_{current_date}.md"
        os.makedirs(folder_path, exist_ok=True)

        # check if the file exists, if so, load it and return it
        if use_existing_file_if_exists and os.path.exists(json_filename):
            add_to_log(f"\U00002714 Using existing file: news_filtered_for_highlights_{current_date}.json")
            with open(json_filename, 'r') as f:
                return json.load(f)
        
        # get the systemprompt
        systemprompt = get_systemprompt(purpose="filter")

        # get all news
        news = get_all_rss_articles(
            use_existing_file_if_exists=use_existing_file_if_exists
            )
        if not news:
            return None

        # prepare message history for LLM, for every article in every news category
        news_with_details = {}
        for category in news:
            if category != "total":
                add_to_log(f"Filtering news for category '{category}' ...")

                news_with_details[category] = {}
                news_with_details[category]["articles"] = []
                news_with_details[category]["tokens"] = 0

                message_history = [
                    {"role": "system", "content":systemprompt},
                    {"role": "user", "content":json.dumps(news[category]["articles"])}
                    ]
                
                # send to LLM and get the filtered articles as json
                response = asyncio.run(ask_llm(
                    message_history=message_history,
                    bot={
                        "user_name": "burton", 
                        "system_prompt": systemprompt, 
                        "creativity": 0, 
                        "model": "gpt-4"
                    },
                    response_format="json",
                    save_request_to_json=True,
                    )
                )

                filtered_articles = response.get("articles")

                # then for every article, open the link and get the text (if it fails, then use the description)
                for article in filtered_articles:
                    article["full_content"] = None
                    if add_full_content:
                        article["full_content"] = get_article_full_text(article["link"])
                    if not article["full_content"]:
                        article["full_content"] = article["description"]

                    news_with_details[category]["articles"].append(article)

                    # add the token count
                    token_count_article = count_tokens(message=json.dumps(article))
                    news_with_details[category]["tokens"] += token_count_article


                # save the news as json if requested
                if save_as_json:
                    with open(json_filename, "w") as f:
                        json.dump(news_with_details, f, indent=4)

        
        
        if return_content == "json":
            return news_with_details

        # generate markdown text with all the news for all categories
        markdowntext = ""
        token_count_markdown = 0
        for category in news_with_details:
            if category != "total":
                markdowntext += f"## {category}\n\n"
                for article_block in news_with_details[category]["article_blocks"]:
                    for article in article_block["articles"]:
                        article_markdown = f"### {article['title']}\n\n{article['full_content']}\n\n"
                        token_count_article = count_tokens(message=article_markdown)
                        if token_count_markdown + token_count_article > 11000:
                            return markdowntext
                        token_count_markdown += token_count_article
                        markdowntext += article_markdown

        # save the news as text if requested
        if save_as_md:
            with open(text_filename, "w") as f:
                f.write(markdowntext)

        return markdowntext
    

    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to get news filtered for highlights.", traceback=traceback.format_exc())



if __name__ == "__main__":
    get_rss_highlights(save_as_json=True, use_existing_file_if_exists=True)