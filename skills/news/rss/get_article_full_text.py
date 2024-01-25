from newspaper import Article, Config
from newspaper.article import ArticleException
import traceback
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *


def get_article_full_text(url: str) -> str:
    try:
        add_to_log(module_name="News | RSS | Get full article text", state="start", color="yellow")
        add_to_log("Getting full article text ...")

        config = load_config()

        # setup the browser user agent
        browser_config = Config()
        browser_config.browser_user_agent = config["user_agent"]["official"]

        # get the article text by loading the website
        article = Article(url=url, config=browser_config)
    
        article.download()
        article.parse()

        add_to_log("Successfully got full article text", state="success")
        return article.text

    except ArticleException:
        if "404" in str(ArticleException):
            add_to_log(f"ArticleException: 404 (not found) - {url}", state="error")
        
        elif "403" in str(ArticleException):
            add_to_log(f"ArticleException: 403 (forbidden) - {url}", state="error")

        else:
            process_error("Failed to get article full text", traceback=traceback.format_exc())
        return None
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to get article full text", traceback=traceback.format_exc())

        return None


if __name__ == "__main__":
    text = get_article_full_text("https://www.businessinsider.de/wirtschaft/chat-gpt-wurde-opfer-eines-hackerangriffs-das-steckt-dahinter/?tpcc=offsite_rss")
    print(text)