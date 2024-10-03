from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from typing import List, Optional, Union, Literal
import re

# POST /skill/docs (create a document skill)

class TextElement(BaseModel):
    """Model for a text element in the document"""
    type: Literal["text"] = Field("text", description="Type of the element")
    text: str = Field(..., description="Text content")
    bold: bool = Field(False, description="Bold formatting")
    italic: bool = Field(False, description="Italic formatting")
    underline: bool = Field(False, description="Underline formatting")
    color: Optional[str] = Field(None, description="Text color in hex format")
    alignment: Optional[Literal["left", "right", "center", "justify"]] = Field(None, description="Text alignment (left, right, center, justify)")
    background_color: Optional[str] = Field(None, description="Background color in hex format")

    @field_validator('color', 'background_color')
    @classmethod
    def validate_color(cls, value):
        if value and not re.match(r'^#(?:[0-9a-fA-F]{3}){1,2}$', value):
            raise ValueError('Color must be in hex format')
        return value

class HeadingElement(BaseModel):
    """Model for a heading element in the document"""
    type: Literal["heading"] = Field("heading", description="Type of the element")
    text: str = Field(..., description="Heading text")
    level: Optional[Literal[1, 2, 3, 4, 5, 6]] = Field(1, description="Heading level (1-6)")
    color: Optional[str] = Field(None, description="Heading color in hex format")
    alignment: Optional[Literal["left", "right", "center", "justify"]] = Field(None, description="Text alignment (left, right, center, justify)")
    background_color: Optional[str] = Field(None, description="Background color in hex format")

    @field_validator('color', 'background_color')
    @classmethod
    def validate_color(cls, value):
        if value and not re.match(r'^#(?:[0-9a-fA-F]{3}){1,2}$', value):
            raise ValueError('Color must be in hex format')
        return value


class HyperlinkElement(BaseModel):
    """Model for a hyperlink element in the document"""
    type: Literal["hyperlink"] = Field("hyperlink", description="Type of the element")
    text: str = Field(..., description="Text for the hyperlink")
    url: str = Field(..., description="URL for the hyperlink")

    @field_validator('url')
    @classmethod
    def validate_url(cls, value):
        if value.startswith('mailto:'):
            email = value[7:]
            if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
                raise ValueError('Invalid email address')
        elif value.startswith('tel:'):
            phone = value[4:]
            if not re.match(r'^\+\d{1,3}\d{4,14}(?:x.+)?$', phone):
                raise ValueError('Invalid phone number format. Must include country code.')
        elif not re.match(r'^(http|https)://', value):
            raise ValueError('URL must start with http, https, mailto, or tel')
        return value

class Size(BaseModel):
    value: float = Field(..., description="Value of the size")
    unit: Literal["in", "cm", "pt"] = Field(..., description="Unit of the size")

class ImageElement(BaseModel):
    """Model for an image element in the document"""
    type: Literal["image"] = Field("image", description="Type of the element")
    url: Optional[str] = Field(None, description="URL of the image")
    base64_file: Optional[str] = Field(None, description="Base64 encoded image file")
    width: Optional[Size] = Field(None, description="Width of the image")
    height: Optional[Size] = Field(None, description="Height of the image")
    alt_text: Optional[str] = Field(None, description="Alternative text for the image")
    margin: Optional[str] = Field(None, description="Margin around the image (e.g., '10px 20px')")
    border: Optional[str] = Field(None, description="Border around the image (e.g., '1px solid #000')")

    @model_validator(mode='after')
    def validate_image_source(cls, values):
        if not values.url and not values.base64_file:
            raise ValueError('Either url or base64_file must be provided')
        return values

    @field_validator('border', 'margin')
    @classmethod
    def validate_border_margin(cls, value):
        if value:
            # Regex to match "1px solid #000", "10px 20px", "10px"
            if not re.match(r'^(\d+(px|em|%)\s*(\d+(px|em|%))?\s*(\d+(px|em|%))?\s*(\d+(px|em|%))?|(\d+px\s+solid\s+#\d{3,6}))$', value):
                raise ValueError('Border and margin must be in a valid CSS format, e.g., "1px solid #000", "10px 20px", or "10px"')
        return value

class FormulaElement(BaseModel):
    """Model for a formula element in the document"""
    type: str = Field("formula", description="Type of the element")
    formula: str = Field(..., description="Formula content")

class TableCell(BaseModel):
    """Model for a cell in a table"""
    content: Union[TextElement, FormulaElement, HeadingElement, HyperlinkElement, ImageElement] = Field(..., description="Content of the table cell")
    background_color: Optional[str] = Field(None, description="Background color in hex format")
    border: Optional[str] = Field(None, description="Border around the cell (e.g., '1px solid #000')")

    @field_validator('background_color')
    @classmethod
    def validate_color(cls, value):
        if value and not re.match(r'^#(?:[0-9a-fA-F]{3}){1,2}$', value):
            raise ValueError('Color must be in hex format')
        return value

    @field_validator('border')
    @classmethod
    def validate_border(cls, value):
        if value and not re.match(r'^\d+(px|em|%)\s*\d*(px|em|%)?\s*\d*(px|em|%)?\s*\d*(px|em|%)?$', value):
            raise ValueError('Border must be in a valid CSS format, e.g., "1px solid #000" or "10px 20px"')
        return value

class TableRow(BaseModel):
    """Model for a row in a table"""
    cells: List[TableCell] = Field(..., description="List of cells in the row")

class TableElement(BaseModel):
    """Model for a table element in the document"""
    type: str = Field("table", description="Type of the element")
    rows: List[TableRow] = Field(..., description="List of rows in the table")
    border: Optional[str] = Field(None, description="Border around the table (e.g., '1px solid #000')")
    margin: Optional[str] = Field(None, description="Margin around the table (e.g., '10px 20px')")

    @field_validator('border', 'margin')
    @classmethod
    def validate_border_margin(cls, value):
        if value:
            # Regex to match "1px solid #000", "10px 20px", "10px"
            if not re.match(r'^(\d+(px|em|%)\s*(\d+(px|em|%))?\s*(\d+(px|em|%))?\s*(\d+(px|em|%))?|(\d+px\s+solid\s+#\d{3,6}))$', value):
                raise ValueError('Border and margin must be in a valid CSS format, e.g., "1px solid #000", "10px 20px", or "10px"')
        return value

class ListItem(BaseModel):
    """Model for an item in a list"""
    content: Union[TextElement, HeadingElement, HyperlinkElement, ImageElement] = Field(..., description="Content of the list item")
    level: Optional[int] = Field(1, description="List level for nested lists")

class ListElement(BaseModel):
    """Model for a list element in the document"""
    type: Literal["list"] = Field("list", description="Type of the element")
    items: List[ListItem] = Field(..., description="List of items")
    ordered: bool = Field(False, description="Whether the list is ordered")

class CodeBlockElement(BaseModel):
    """Model for a code block element in the document"""
    type: Literal["code_block"] = Field("code_block", description="Type of the element")
    code: str = Field(..., description="Code content")
    language: Optional[str] = Field(None, description="Programming language of the code")

class BlockQuoteElement(BaseModel):
    """Model for a block quote element in the document"""
    type: Literal["block_quote"] = Field("block_quote", description="Type of the element")
    text: str = Field(..., description="Quote text")
    author: Optional[str] = Field(None, description="Author of the quote")

class PageBreakElement(BaseModel):
    """Model for a page break element in the document"""
    type: Literal["page_break"] = Field("page_break", description="Type of the element")
    break_type: Literal["page"] = Field("page", description="Type of break, e.g., 'page'")

class DocsCreateInput(BaseModel):
    """Model for a document creation input"""
    title: str = Field(..., description="Title of the document")
    elements: List[Union[
        TextElement, HeadingElement, HyperlinkElement, ImageElement,
        TableElement, ListElement, CodeBlockElement, BlockQuoteElement,
        PageBreakElement
    ]] = Field(..., description="List of elements in the document")

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode='before')
    def validate_elements(cls, values):
        elements = values.get('elements', [])
        for element in elements:
            element_type = element.get('type')
            if element_type == 'text':
                TextElement(**element)
            elif element_type == 'heading':
                HeadingElement(**element)
            elif element_type == 'hyperlink':
                HyperlinkElement(**element)
            elif element_type == 'image':
                ImageElement(**element)
            elif element_type == 'table':
                TableElement(**element)
            elif element_type == 'list':
                ListElement(**element)
            elif element_type == 'code_block':
                CodeBlockElement(**element)
            elif element_type == 'block_quote':
                BlockQuoteElement(**element)
            elif element_type == 'page_break':
                PageBreakElement(**element)
            else:
                raise ValueError(f"Unknown element type: {element_type}")
        return values

    @model_validator(mode='after')
    def validate_document(cls, values):
        # Example validation: Ensure at least one element is present
        if not values.elements:
            raise ValueError('Document must contain at least one element')
        return values


# Example of a document creation payload
docs_create_input_example = {
    "title": "Project Proposal",
    "elements": [
        {"type": "text", "text": "Introduction to the project.", "bold": True, "italic": True, "underline": False, "color": "#333333", "alignment": "justify", "background_color": "#F0F0F0"},
        {"type": "heading", "text": "Project Goals", "level": 2, "color": "#0000FF", "alignment": "left", "background_color": "#FFFFFF"},
        {"type": "hyperlink", "text": "Visit our website", "url": "https://example.com"},
        {"type": "hyperlink", "text": "Contact Us", "url": "mailto:contact@example.com"},
        {"type": "hyperlink", "text": "Support Line", "url": "tel:+18005551234"},
        {"type": "image", "url": "https://example.com/logo.png", "width": {"value": 5, "unit": "cm"}, "height": {"value": 5, "unit": "cm"}, "alt_text": "Company Logo", "margin": "10px 20px", "border": "2px solid #000"},
        {
            "type": "table",
            "rows": [
                {"cells": [{"content": {"type": "text", "text": "Task"}}, {"content": {"type": "text", "text": "Deadline"}}]},
                {"cells": [{"content": {"type": "text", "text": "Design Phase"}}, {"content": {"type": "text", "text": "2023-12-01"}}]},
                {"cells": [{"content": {"type": "text", "text": "Development Phase"}}, {"content": {"type": "formula", "formula": "=TODAY()+30"}}]}
            ],
            "border": "1px solid #000",
            "margin": "15px"
        },
        {"type": "page_break"},
        {"type": "list", "items": [{"content": {"type": "text", "text": "Requirement Analysis"}, "level": 1}, {"content": {"type": "text", "text": "System Design"}, "level": 1}], "ordered": True},
        {"type": "code_block", "code": "def main():\n    print('Project Proposal')", "language": "python"},
        {"type": "block_quote", "text": "The best way to predict the future is to invent it.", "author": "Alan Kay"}
    ]
}

docs_create_output_example = {
    "name": "project_proposal.docx",
    "url": "/v1/openmatesdevs/apps/files/docs/project_proposal.docx",
    "expiration_datetime": "2024-01-01T00:00:00Z",
    "access_public": False,
    "read_access_limited_to_teams": ["openmatesdevs"],
    "read_access_limited_to_users": None,
    "write_access_limited_to_teams": ["openmatesdevs"],
    "write_access_limited_to_users": None
}