import os
import yaml
from dotenv import load_dotenv
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, inch
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics

from app.services.translations import TranslationService
from app.services.email.config_loader import load_shared_urls
from app.services.pdf.flowables import ColoredLine
from app.services.pdf.utils import (sanitize_html_for_reportlab, replace_placeholders_safely, 
                                   format_date_for_locale, format_credits, format_link_safely)

class BasePDFTemplateService:
    def __init__(self):
        # Initialize translation service
        self.translation_service = TranslationService()
        
        # Load shared URLs configuration
        self.shared_urls = load_shared_urls().get('urls', {})
        
        # Get sender details from environment variables - with defaults for safety
        self.sender_addressline1 = os.getenv("INVOICE_SENDER_ADDRESSLINE1", "")
        self.sender_addressline2 = os.getenv("INVOICE_SENDER_ADDRESSLINE2", "")
        self.sender_addressline3 = os.getenv("INVOICE_SENDER_ADDRESSLINE3", "")
        self.sender_country = os.getenv("INVOICE_SENDER_COUNTRY", "")
        self.sender_email = self.shared_urls.get('contact', {}).get('email', "support@openmates.org")
        self.sender_vat = os.getenv("INVOICE_SENDER_VAT", "")
        
        # Get Discord URL from shared config
        self.discord_url = self.shared_urls.get('contact', {}).get('discord', "")
        self.discord_group_invite_code = self.discord_url.split("/")[-1]
        
        # Register both regular and bold fonts
        self.regular_font_path = os.path.join(os.path.dirname(__file__), "..", "fonts", "LexendDeca-Regular.ttf")
        self.bold_font_path = os.path.join(os.path.dirname(__file__), "..", "fonts", "LexendDeca-Bold.ttf")
        
        # Define languages not supported by LexendDeca (primarily CJK languages)
        self.unsupported_languages = ['ja', 'zh', 'ko', 'zh-Hans', 'zh-Hant', 'ar', 'th', 'hi']
        
        # Register fonts
        pdfmetrics.registerFont(TTFont('LexendDeca', self.regular_font_path))
        pdfmetrics.registerFont(TTFont('LexendDeca-Bold', self.bold_font_path))
        
        # Create font family to link the fonts
        pdfmetrics.registerFontFamily('LexendDeca', normal='LexendDeca', bold='LexendDeca-Bold')
        
        self.styles = getSampleStyleSheet()
        
        # Modify existing styles
        self.styles['Normal'].fontName = 'LexendDeca'
        self.styles['Normal'].fontSize = 10
        
        # Create bold style
        self.styles.add(ParagraphStyle(name='Bold', 
                                      parent=self.styles['Normal'],
                                      fontName='LexendDeca-Bold'))
        
        # Modify Heading1 to use bold font
        self.styles['Heading1'].fontName = 'LexendDeca-Bold'
        self.styles['Heading1'].fontSize = 20
        
        # Modify or add Heading2 for OpenMates text
        if 'Heading2' in self.styles:
            self.styles['Heading2'].fontName = 'LexendDeca-Bold'
            self.styles['Heading2'].fontSize = 27
            self.styles['Heading2'].alignment = 2  # Right align
        else:
            self.styles.add(ParagraphStyle(name='Heading2', 
                                          fontName='LexendDeca-Bold', 
                                          fontSize=27, 
                                          alignment=2))
        
        # Add additional styles
        self.styles.add(ParagraphStyle(name='ColorLinks', 
                                      parent=self.styles['Normal'],
                                      textColor=colors.HexColor("#4867CD")))
        
        self.styles.add(ParagraphStyle(name='FooterText', 
                                      parent=self.styles['Normal'],
                                      textColor=colors.HexColor("#848484")))
        
        # Define colors
        self.top_line_color = colors.HexColor("#5951D0")
        self.bottom_line_color = colors.HexColor("#7D74FF")
        self.separator_color = colors.HexColor("#5951D0")
        self.open_color = colors.HexColor("#4867CD")
        
        # Define URLs
        self.start_chat_with_help_mate_link = self.shared_urls.get('base', {}).get('webapp', {}).get('production', "https://app.openmates.org")
        self.email_address = self.sender_email
        
        # Define line height for top and bottom bars
        self.line_height = 9
        
        # Add a small left indent to align elements properly
        self.left_indent = 10
        
        # Load pricing config
        self.pricing_tiers = self._load_pricing_config()
        
        # Set current language to default of English
        self.current_lang = "en"
        
        # Placeholder for translations
        self.t = {}
        
    def _draw_header_footer(self, canvas, doc):
        """Draw the colored bars at the top and bottom of the page"""
        width, height = A4
        
        # Draw top line at the absolute top of the page
        canvas.setFillColor(self.top_line_color)
        canvas.rect(0, height - self.line_height, width, self.line_height, fill=1, stroke=0)
        
        # Draw bottom line at the absolute bottom of the page
        canvas.setFillColor(self.bottom_line_color)
        canvas.rect(0, 0, width, self.line_height, fill=1, stroke=0)
        
        # Show translation disclaimer for non-English languages
        if self.current_lang != "en":
            # Translation disclaimer text will be set by the child class
            disclaimer_text = self.get_translation_disclaimer()
            
            # Convert <br> tags to line breaks for direct canvas writing
            disclaimer_lines = disclaimer_text.replace("<br>", "<br/>").split("<br/>")
            
            canvas.setFont('LexendDeca', 10)
            canvas.setFillColor(colors.HexColor("#848484"))
            
            # Calculate x position to align with document content (doc's left margin + self.left_indent)
            x_position = 36 + self.left_indent  # Match the left alignment of the main content
            
            y_position = self.line_height + 25
            for line in disclaimer_lines:
                canvas.drawString(x_position, y_position, line)
                y_position -= 12
    
    def get_translation_disclaimer(self):
        """Get the translation disclaimer text - to be overridden by child classes"""
        raise NotImplementedError("Subclasses must implement this method")
    
    def _get_translated_country_name(self, country_name):
        """Get translated country name from translations"""
        if not country_name:
            return ""
            
        # Convert country name to lowercase and remove spaces for translation key
        country_key = country_name.lower().replace(" ", "_")
        
        # Try to get translation
        try:
            return self.t["invoices_and_credit_notes"][country_key]["text"]
        except (KeyError, TypeError):
            # Return original country name if translation not found
            return country_name
        
    def _is_language_supported(self, lang):
        """Check if a language is supported by LexendDeca font"""
        return lang not in self.unsupported_languages

    def _build_address_string(self, data_dict):
        """Build an address string from dictionary values, only including non-empty fields"""
        lines = []
        
        # Add non-empty fields to lines array
        for key, value in data_dict.items():
            if value and value.strip():
                lines.append(value.strip())
                
        # Join non-empty lines with HTML line breaks
        return "<br/>".join(lines)

    def _load_pricing_config(self):
        """Load pricing configuration from shared YAML file"""
        shared_pricing_path = '/shared/config/pricing.yml'
        try:
            with open(shared_pricing_path, 'r') as file:
                config = yaml.safe_load(file)
                return config.get('pricingTiers', [])
        except Exception as e:
            print(f"Error loading pricing config from {shared_pricing_path}: {e}")
            return []

    def _validate_credits(self, credits):
        """Validate credits against available pricing tiers"""
        valid_credits = [tier.get('credits') for tier in self.pricing_tiers]
        if not valid_credits:
            # If we couldn't load pricing tiers, just return the original value
            return credits
            
        if credits in valid_credits:
            return credits
            
        # If credits value is invalid, use the closest valid value
        closest = min(valid_credits, key=lambda x: abs(x - credits))
        print(f"Warning: Invalid credit amount {credits}, using closest valid value: {closest}")
        return closest

    def _get_price_for_credits(self, credits, currency='eur'):
        """Get the price for the given credit amount from pricing config"""
        # Normalize currency to lowercase
        currency = currency.lower()
        
        for tier in self.pricing_tiers:
            if tier.get('credits') == credits:
                # Return the price in the specified currency or 0 if currency not found
                return tier.get('price', {}).get(currency, 0)
        
        # If we can't find the exact match (shouldn't happen after validation)
        print(f"Warning: No price found for {credits} credits in {currency}")
        return 0
        
    def build_questions_helper_section(self, elements, doc):
        """Build questions helper section that's common between invoice and credit note"""
        # Convert question helpers to paragraphs with proper links - fix <br> tags
        questions_helper_texts = [
            # First paragraph doesn't need replacements
            {
                "text": f"<b>{sanitize_html_for_reportlab(self.t['invoices_and_credit_notes']['if_you_have_questions']['text'])}</b>",
                "style": self.styles['Normal'],
                "replacements": {}
            },
            # Second paragraph with safe placeholder replacement - as bullet point
            {
                "text": "• " + self.t['invoices_and_credit_notes']['ask_team_mates']['text'],
                "style": self.styles['Normal'],
                "replacements": {
                    "{start_chat_with_help_mate_link}": self.start_chat_with_help_mate_link
                }
            },
            # Third paragraph doesn't need replacements - as bullet point
            {
                "text": "• " + self.t['invoices_and_credit_notes']['check_the_documentation']['text'],
                "style": self.styles['Normal'],
                "replacements": {}
            },
            # Fourth paragraph with safe placeholder replacement - as bullet point
            {
                "text": "• " + self.t['invoices_and_credit_notes']['ask_in_discord']['text'],
                "style": self.styles['Normal'],
                "replacements": {
                    "{discord_group_invite_code}": self.discord_group_invite_code
                }
            },
            # Fifth paragraph with safe placeholder replacement - as bullet point
            {
                "text": "• " + self.t['invoices_and_credit_notes']['contact_via_email']['text'],
                "style": self.styles['Normal'],
                "replacements": {
                    "{email_address}": self.email_address
                }
            }
        ]
        
        # Process each question helper with appropriate replacements
        questions_helper = []
        for helper_data in questions_helper_texts:
            # Apply replacements safely (respecting HTML structure)
            processed_text = replace_placeholders_safely(
                helper_data["text"],
                helper_data["replacements"]
            )
            
            # Sanitize the HTML
            sanitized_text = sanitize_html_for_reportlab(processed_text)
            
            try:
                # Create paragraph with error handling
                paragraph = Paragraph(sanitized_text, helper_data["style"])
                questions_helper.append(paragraph)
            except Exception as e:
                # Log the error for debugging
                print(f"Error creating paragraph: {e}")
                print(f"Problematic text: {sanitized_text}")
                # Use a simpler fallback
                fallback = "Please contact support@openmates.org if you have questions."
                questions_helper.append(Paragraph(fallback, self.styles['Normal']))

        # Add each question helper as a separate row
        for helper_text in questions_helper:
            helper_table = Table([[Spacer(self.left_indent, 0), helper_text]], 
                               colWidths=[self.left_indent, doc.width-self.left_indent])
            helper_table.setStyle(TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (1, 0), (1, 0), 2),
            ]))
            elements.append(helper_table)
