import requests
from bs4 import BeautifulSoup

def get_website_social_image(url: str) -> str:
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    meta_tag = soup.find('meta', attrs={'property': 'og:image'})
    if meta_tag:
        return meta_tag['content']
    else:
        return "No social image found"
    
if __name__ == "__main__":
    url = "https://www.businessinsider.de/wirtschaft/chat-gpt-wurde-opfer-eines-hackerangriffs-das-steckt-dahinter/?tpcc=offsite_rss"
    social_image = get_website_social_image(url)
    print(social_image)