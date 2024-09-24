from playwright.async_api import BrowserContext, Browser

async def new_context(browser: Browser) -> BrowserContext:
    return await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    )