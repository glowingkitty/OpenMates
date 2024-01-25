import requests
from bs4 import BeautifulSoup

def get_website_logo(url: str) -> str:
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')

    link = soup.find('link', rel='icon')
    if link is None:
        link = soup.find('link', rel='shortcut icon')

    if link is not None:
        logo_url = link.get('href')
        if not logo_url.startswith('http'):
            if logo_url.startswith('/'):
                logo_url = url + logo_url
            else:
                logo_url = url + '/' + logo_url
        return logo_url

    return None

if __name__ == "__main__":
    url = "https://www.businessinsider.de/wirtschaft/chat-gpt-wurde-opfer-eines-hackerangriffs-das-steckt-dahinter/?tpcc=offsite_rss"
    logo_url = get_website_logo(url)
    print(logo_url)