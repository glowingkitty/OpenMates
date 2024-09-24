from pydantic import BaseModel, Field
from typing import List, Optional, Union, Literal

# GET /skill/web/view (view a web page)

class NavBarLink(BaseModel):
    """This is the model for the navigation bar link of the web page"""
    type: Literal["navbar_link"] = Field("navbar_link", description="Type of the navigation bar link")
    title: str = Field(..., description="Title of the navigation bar link")
    url: str = Field(..., description="URL of the navigation bar link")

class NavBar(BaseModel):
    """This is the model for the navigation bar of the web page"""
    type: Literal["navbar"] = Field("navbar", description="Type of the navigation bar")
    links: List[NavBarLink] = Field(..., description="List of links in the navigation bar")

class ContentBlock(BaseModel):
    """This is the model for the content block of the web page"""
    type: Literal["content_block"] = Field("content_block", description="Type of the content block")
    content: str = Field(..., description="Content of the content block")

class WebViewInput(BaseModel):
    """This is the model for the input of the web view skill"""
    url: str = Field(..., description="URL of the web page")

class WebViewOutput(BaseModel):
    """This is the model for the output of the web view skill"""
    url: str = Field(..., description="URL of the web page")
    title: str = Field(..., description="Title of the web page")
    description: Optional[str] = Field(None, description="Description of the web page")
    keywords: Optional[List[str]] = Field(None, description="Keywords of the web page")
    authors: Optional[List[str]] = Field(None, description="Authors of the web page")
    publisher: Optional[str] = Field(None, description="Publisher of the web page")
    published_date: Optional[str] = Field(None, description="Published date of the web page")
    elements: List[Union[
        NavBar, ContentBlock
    ]] = Field(None, description="List of elements in the web page")



web_view_input_examples = [
    "https://www.theverge.com/2024/9/20/24248356/iphone-16-camera-photographic-styles",
    "https://www.theverge.com/2024/9/20/24249856/battery-ev-renewable-energy-doe-funding",
    "https://www.tagesschau.de/inland/gesellschaft/fridays-for-future-254.html",
    "https://www.anthropic.com/news/claude-3-5-sonnet"
]

web_view_input_example = {
    "url": "https://www.anthropic.com/news/claude-3-5-sonnet"
}

web_view_output_example = {
    "url": "https://www.anthropic.com/news/claude-3-5-sonnet",
    "title": "Introducing Claude 3.5 Sonnet",
    "description": "Introducing Claude 3.5 Sonnet—our most intelligent model yet. Sonnet now outperforms competitor models and Claude 3 Opus on key evaluations, at twice the speed.",
    "keywords": [],
    "authors": [],
    "publisher": "https://www.anthropic.com",
    "published_date": None,
    "elements": [
        {
            "type": "navbar",
            "links": [
                {
                    "type": "navbar_link",
                    "title": "Home",
                    "url": "https://www.anthropic.com"
                },
                {
                    "type": "navbar_link",
                    "title": "Research",
                    "url": "https://www.anthropic.com/research"
                },
                {
                    "type": "navbar_link",
                    "title": "Company",
                    "url": "https://www.anthropic.com/company"
                },
                {
                    "type": "navbar_link",
                    "title": "Careers",
                    "url": "https://www.anthropic.com/careers"
                },
                {
                    "type": "navbar_link",
                    "title": "News",
                    "url": "https://www.anthropic.com/news"
                }
            ]
        },
        {
            "type": "content_block",
            "content": "Introducing Claude 3.5 Sonnet—our most intelligent model yet. Sonnet now outperforms competitor models and Claude 3 Opus on key evaluations, at twice the speed."
        }
    ]
}