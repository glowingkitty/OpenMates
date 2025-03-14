import os
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
import io
import re
import datetime
import locale
from babel.dates import format_date

from app.services.translations import TranslationService
from app.services.email.config_loader import load_shared_urls


class ColoredLine(Flowable):
    """Custom flowable for drawing colored lines"""
    def __init__(self, width, height, color):
        Flowable.__init__(self)
        self.width = width
        self.height = height
        self.color = color
        
    def draw(self):
        self.canv.setFillColor(self.color)
        self.canv.rect(0, 0, self.width, self.height, fill=1, stroke=0)

class InvoiceTemplateService:
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
        self.regular_font_path = os.path.join(os.path.dirname(__file__), "fonts", "LexendDeca-Regular.ttf")
        self.bold_font_path = os.path.join(os.path.dirname(__file__), "fonts", "LexendDeca-Bold.ttf")
        
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
                                      textColor=colors.HexColor("#7D74FF")))
        
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
        
    def _sanitize_html_for_reportlab(self, text):
        """
        Sanitize HTML for ReportLab compatibility
        
        Args:
            text: HTML text to sanitize
            
        Returns:
            Sanitized text compatible with ReportLab
        """
        if not isinstance(text, str):
            return text
            
        # Fix common HTML issues
        text = text.replace("<br>", "<br/>")
        text = text.replace("<br{", "<br/>{")
        
        # Remove any unclosed tags to prevent parsing errors
        unclosed_pattern = r'<([a-zA-Z]+)(?![^<>]*>)'
        text = re.sub(unclosed_pattern, r'', text)
        
        return text

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
            # Use translated disclaimer text
            disclaimer_text = self.t["invoices_and_credit_notes"]["this_invoice_is_a_translation"]["text"]
            
            # Convert <br> tags to line breaks for direct canvas writing
            disclaimer_lines = disclaimer_text.replace("<br>", "<br/>").split("<br/>")
            
            canvas.setFont('LexendDeca', 10)
            canvas.setFillColor(colors.HexColor("#848484"))
            
            y_position = self.line_height + 25
            for line in disclaimer_lines:
                canvas.drawString(40, y_position, line)
                y_position -= 12

    def _format_date_for_locale(self, date_str, lang='en'):
        """
        Format date based on locale
        
        Args:
            date_str: Date in string format (YYYY-MM-DD)
            lang: Language code for formatting
            
        Returns:
            Formatted date string according to locale
        """
        try:
            # Parse the date string into a datetime object
            date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            
            # Format the date according to the locale
            # Use format='long' to get the full month name with appropriate formatting per locale
            return format_date(date_obj, format='long', locale=lang)
        except Exception as e:
            # Log the error for debugging
            print(f"Date formatting error: {e}")
            # Return original string if formatting fails
            return date_str

    def _get_translated_country_name(self, country_name):
        """
        Get translated country name from translations
        
        Args:
            country_name: Original country name
            
        Returns:
            Translated country name or original if translation not found
        """
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
        """Check if a language is supported by LexendDeca font
        
        Args:
            lang: Language code to check
            
        Returns:
            True if the language is supported, False otherwise
        """
        return lang not in self.unsupported_languages

    def _build_address_string(self, data_dict):
        """
        Build an address string from dictionary values, 
        only including non-empty fields
        
        Args:
            data_dict: Dictionary containing address fields
            
        Returns:
            String with HTML line breaks, with no empty lines
        """
        lines = []
        
        # Add non-empty fields to lines array
        for key, value in data_dict.items():
            if value and value.strip():
                lines.append(value.strip())
                
        # Join non-empty lines with HTML line breaks
        return "<br/>".join(lines)

    def generate_invoice(self, invoice_data, lang="en"):
        """Generate an invoice PDF with the specified language"""
        # Check if language is supported, fall back to English if not
        if not self._is_language_supported(lang):
            # Fall back to English silently
            lang = "en"
        
        # Set current language for use in _draw_header_footer
        self.current_lang = lang
        
        # Get translations
        self.t = self.translation_service.get_translations(lang, variables={
            "card_provider": invoice_data.get("card_name", ""),
            "last_four_digits": invoice_data.get("card_last4", ""),
            "email_address": self.email_address,
            "discord_group_invite_code": self.discord_group_invite_code,
            "start_chat_with_help_mate_link": self.start_chat_with_help_mate_link,
            "amount": invoice_data.get("credits", 0)
        })
        
        buffer = io.BytesIO()
        
        # Use the whole page width and adjust margins - reduced top margin
        doc = SimpleDocTemplate(
            buffer, 
            pagesize=A4,
            leftMargin=36,  # Keep standard left margin
            rightMargin=36,
            topMargin=20 + self.line_height,  # Reduced top margin to move content up
            bottomMargin=36 + self.line_height  # Add the line height to the bottom margin
        )
        
        elements = []
        
        # Reduce the initial spacer to move content up
        elements.append(Spacer(1, 5))  # Reduced from 20 to 5
        
        # Create header with Invoice and OpenMates side by side - no extra padding
        invoice_text = Paragraph(self._sanitize_html_for_reportlab(self.t["invoices_and_credit_notes"]["invoice"]["text"]), self.styles['Heading1'])
        
        # Create a custom paragraph with two differently colored parts for "OpenMates"
        open_text = '<font color="#4867CD">Open</font><font color="black">Mates</font>'
        openmates_text = Paragraph(open_text, self.styles['Heading2'])
        
        # Add left indent to invoice_text and adjust widths to match inner tables
        header_table = Table([[Spacer(self.left_indent, 0), invoice_text, openmates_text]], 
                            colWidths=[self.left_indent, (doc.width-self.left_indent)*0.5, (doc.width-self.left_indent)*0.5])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 24))
        
        # Fix invoice details alignment to match other elements
        # Calculate dynamic width based on text length
        invoice_number_text = self.t["invoices_and_credit_notes"]["invoice_number"]["text"] + ":"
        date_issue_text = self.t["invoices_and_credit_notes"]["date_of_issue"]["text"] + ":"
        date_due_text = self.t["invoices_and_credit_notes"]["date_due"]["text"] + ":"
        
        # Estimate appropriate column width based on longest text plus some padding
        # This gives extra space between label and value, prevents crowding
        label_texts = [invoice_number_text, date_issue_text, date_due_text]
        max_text_len = max(len(text) for text in label_texts)
        # Scale factor: approximately 6 points per character (depends on font)
        label_col_width = max_text_len * 6 + 20  # Add padding
        
        invoice_table = Table([
            [Spacer(self.left_indent, 0), Paragraph(invoice_number_text, self.styles['Normal']), 
             Paragraph(invoice_data['invoice_number'], self.styles['Normal'])],
            [Spacer(self.left_indent, 0), Paragraph(date_issue_text, self.styles['Normal']), 
             Paragraph(self._format_date_for_locale(invoice_data['date_of_issue'], self.current_lang), self.styles['Normal'])],
            [Spacer(self.left_indent, 0), Paragraph(date_due_text, self.styles['Normal']), 
             Paragraph(self._format_date_for_locale(invoice_data['date_due'], self.current_lang), self.styles['Normal'])]
        ], colWidths=[self.left_indent, label_col_width, doc.width-self.left_indent-label_col_width])
        
        invoice_table.setStyle(TableStyle([
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('ALIGN', (2, 0), (2, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(invoice_table)
        elements.append(Spacer(1, 24))
        
        # Create sender details string using environment variables and translated country
        translated_sender_country = self._get_translated_country_name(self.sender_country)
        sender_details_str = f"{self.sender_addressline1}<br/>{self.sender_addressline2}<br/>{self.sender_addressline3}<br/>{translated_sender_country}<br/>{self.sender_email}<br/>{self.t['invoices_and_credit_notes']['vat']['text']}: {self.sender_vat}"
        
        # Create three-column layout without extra padding
        sender_title = Paragraph("<b>OpenMates</b>", self.styles['Bold'])
        sender_details = Paragraph(sender_details_str, self.styles['Normal'])
        
        bill_to_title = Paragraph(f"<b>{self.t['invoices_and_credit_notes']['bill_to']['text']}</b>", self.styles['Bold'])
        
        # Get translated receiver country if it exists
        translated_receiver_country = ""
        if invoice_data.get('receiver_country'):
            translated_receiver_country = self._get_translated_country_name(invoice_data['receiver_country'])
        
        # Build receiver details with only non-empty fields
        receiver_fields = []
        
        # Add name if present
        if invoice_data.get('receiver_name'):
            receiver_fields.append(invoice_data['receiver_name'])
            
        # Add address if present
        if invoice_data.get('receiver_address'):
            receiver_fields.append(invoice_data['receiver_address'])
            
        # Add city if present
        if invoice_data.get('receiver_city'):
            receiver_fields.append(invoice_data['receiver_city'])
            
        # Add country if present
        if translated_receiver_country:
            receiver_fields.append(translated_receiver_country)
            
        # Add email if present
        if invoice_data.get('receiver_email'):
            receiver_fields.append(invoice_data['receiver_email'])
            
        # Add VAT if present
        if invoice_data.get('receiver_vat'):
            receiver_fields.append(f"{self.t['invoices_and_credit_notes']['vat']['text']}: {invoice_data['receiver_vat']}")
        
        # Join all non-empty fields with line breaks
        receiver_details_str = "<br/>".join(receiver_fields)
        receiver_details = Paragraph(receiver_details_str, self.styles['Normal'])
        
        usage_title = Paragraph(f"<b>{self.t['invoices_and_credit_notes']['view_usage']['text']}:</b>", self.styles['Bold'])
        
        # Format URL properly with line break while maintaining a single clickable link
        url = invoice_data['qr_code_url']
        # Find a good spot to split the URL - after the domain
        split_index = url.find('/', 8)  # Find first '/' after http(s)://
        if (split_index != -1):
            formatted_url = f"<a href='{url}'>{url[:split_index+1]}<br/>{url[split_index+1:]}</a>"
        else:
            formatted_url = f"<a href='{url}'>{url}</a>"
            
        usage_url = Paragraph(formatted_url, self.styles['Normal'])
        
        # Generate QR code
        qr_code = QrCodeWidget(invoice_data['qr_code_url'])
        bounds = qr_code.getBounds()
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        # Modify the Drawing to start from the absolute left (x=0)
        d = Drawing(70, 70, transform=[70./width, 0, 0, 70./height, 0, 0])
        d.add(qr_code)
        
        # Create tables for each column
        sender_table = Table([[sender_title], [sender_details]])
        sender_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (0, 0), 6),
        ]))
        
        receiver_table = Table([[bill_to_title], [receiver_details]])
        receiver_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (0, 0), 6),
        ]))
        
        usage_table = Table([
            [usage_title], 
            [usage_url], 
            [d]
        ])
        usage_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            # Set explicit zero padding for all cells, especially the QR code cell
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (0, 0), 6),
            # Special negative padding for QR code to force left alignment
            ('LEFTPADDING', (0, 2), (0, 2), -7),
        ]))
        
        # Add left indent to info table
        info_table_with_indent = Table([
            [Spacer(self.left_indent, 0), sender_table, receiver_table, usage_table]
        ], colWidths=[self.left_indent, (doc.width-self.left_indent)/3, (doc.width-self.left_indent)/3, (doc.width-self.left_indent)/3])
        
        info_table_with_indent.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(info_table_with_indent)
        
        # Add separator line
        elements.append(Spacer(1, 24))
        
        # Add item details without extra padding
        column_headers = [
            Paragraph(f"<b>{self._sanitize_html_for_reportlab(self.t['invoices_and_credit_notes']['description']['text'])}</b>", self.styles['Bold']),
            Paragraph(f"<b>{self._sanitize_html_for_reportlab(self.t['invoices_and_credit_notes']['quantity']['text'])}</b>", self.styles['Bold']),
            Paragraph(f"<b>{self._sanitize_html_for_reportlab(self.t['invoices_and_credit_notes']['unit_price_no_tax']['text'])}</b>", self.styles['Bold']),
            Paragraph(f"<b>{self._sanitize_html_for_reportlab(self.t['invoices_and_credit_notes']['total_price_no_tax']['text'])}</b>", self.styles['Bold'])
        ]
        
        # Format the credits text using the translation
        credits_text = self._sanitize_html_for_reportlab(
            self.t["invoices_and_credit_notes"]["credits_item"]["text"].replace("{amount}", str(invoice_data['credits']))
        )
        
        data_row = [
            Paragraph(credits_text, self.styles['Normal']),
            Paragraph("1x", self.styles['Normal']),
            Paragraph(f"€{invoice_data['unit_price']:.2f}", self.styles['Normal']),
            Paragraph(f"€{invoice_data['total_price']:.2f}", self.styles['Normal'])
        ]
        
        # Create table with proper indent
        inner_table = Table([column_headers, data_row], 
                          colWidths=[(doc.width-self.left_indent)*0.55,  # Description takes 55% (decreased)
                                     (doc.width-self.left_indent)*0.15,  # Quantity takes 15% (increased)
                                     (doc.width-self.left_indent)*0.15,  # Unit price takes 15%
                                     (doc.width-self.left_indent)*0.15]) # Total takes 15%
        inner_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (2, 0), (3, -1), 'CENTER'),  # Center align Unit price and Total columns
            ('VALIGN', (0, 0), (-1, 0), 'BOTTOM'), # Align headers to bottom
            ('VALIGN', (0, 1), (-1, -1), 'MIDDLE'), # Keep data row centered vertically
            ('LINEBELOW', (0, 0), (-1, 0), 1, self.separator_color),  # Only line below headers
            ('BOTTOMPADDING', (0, 0), (-1, 0), 5),  # Reduced from 12 to 5 to bring header text closer to line
            ('TOPPADDING', (0, 1), (-1, 1), 8),    # Add padding above data row to increase spacing
            ('TOPPADDING', (0, 0), (-1, 0), 0),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ]))
        
        # Add indent to table - restore normal left alignment
        padded_table = Table([[Spacer(self.left_indent, 0), inner_table]], 
                            colWidths=[self.left_indent, doc.width-self.left_indent])
        padded_table.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(padded_table)
        
        # Add totals table starting at 45% of document width
        total_start_position = doc.width * 0.45
        left_space = total_start_position - self.left_indent
        
        # Create data for totals table - remove bold from first two rows
        totals_data = [
            [Paragraph(self.t['invoices_and_credit_notes']['total_excl_tax']['text'], self.styles['Normal']), 
             Paragraph(f"€{invoice_data['total_price']:.2f}", self.styles['Normal'])],
            [Paragraph(self.t["invoices_and_credit_notes"]["vat_rate"]["text"] + " *", self.styles['Normal']), 
             Paragraph("€0.00", self.styles['Normal'])],
            [Paragraph(f"<b>{self.t['invoices_and_credit_notes']['total_paid']['text']}</b>", self.styles['Bold']), 
             Paragraph(f"<b>€{invoice_data['total_price']:.2f}</b>", self.styles['Bold'])]
        ]
        
        # Calculate column widths for the totals table
        totals_width = doc.width - total_start_position
        totals_col1_width = totals_width * 0.75  # Increased from 0.65 to 0.75
        totals_col2_width = totals_width * 0.25  # Decreased from 0.35 to 0.25
        
        # Create the totals table
        totals_inner_table = Table(totals_data, 
                                  colWidths=[totals_col1_width, totals_col2_width])
        
        totals_inner_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            # Remove line above first row
            ('LINEABOVE', (0, 2), (-1, 2), 1, self.separator_color), # Line above total paid row only
            ('LINEBELOW', (0, 2), (-1, 2), 1, self.separator_color), # Line below total paid row
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        
        # Add totals table with proper positioning
        totals_table = Table([[Spacer(self.left_indent, 0), 
                             Spacer(left_space - self.left_indent, 0),
                             totals_inner_table]], 
                            colWidths=[self.left_indent, left_space - self.left_indent, totals_width])
        
        totals_table.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        
        elements.append(Spacer(1, 10))
        elements.append(totals_table)
        elements.append(Spacer(1, 10))
        
        # Add payment details with translation - fix <br> tags
        # Special handling for the paid_with text that might contain unclosed br tags
        paid_with_text = self.t["invoices_and_credit_notes"]["paid_with"]["text"]
        
        # First fix any potential HTML issues
        if "<br{" in paid_with_text:
            paid_with_text = paid_with_text.replace("<br{", "<br/>{") 
        
        # Now replace variables
        paid_with_text = paid_with_text.replace("{card_provider}", invoice_data["card_name"])
        paid_with_text = paid_with_text.replace("{last_four_digits}", invoice_data["card_last4"])
        
        # Finally sanitize the HTML
        paid_with_text = self._sanitize_html_for_reportlab(paid_with_text)
        
        try:
            # Create paragraph with error catching
            paid_with_paragraph = Paragraph(paid_with_text, self.styles['Normal'])
            payment_table = Table([[Spacer(self.left_indent, 0), paid_with_paragraph]], 
                                 colWidths=[self.left_indent, doc.width-self.left_indent])
        except Exception as e:
            # Fallback to plain text if HTML parsing fails
            fallback_text = f"Paid with: {invoice_data['card_name']} card ending in {invoice_data['card_last4']}"
            payment_table = Table([[Spacer(self.left_indent, 0), 
                                  Paragraph(fallback_text, self.styles['Normal'])]], 
                                  colWidths=[self.left_indent, doc.width-self.left_indent])
        
        payment_table.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(payment_table)
        
        # Add contact information with questions helper
        elements.append(Spacer(1, 24))
        
        # Convert question helpers to paragraphs with proper links - fix <br> tags
        questions_helper = [
            Paragraph(f"<b>{self._sanitize_html_for_reportlab(self.t['invoices_and_credit_notes']['if_you_have_questions']['text'])}</b>", self.styles['Bold']),
            Paragraph(self._sanitize_html_for_reportlab(
                self.t['invoices_and_credit_notes']['ask_team_mates']['text']
                .replace("{start_chat_with_help_mate_link}", self.start_chat_with_help_mate_link)
            ), self.styles['Normal']),
            Paragraph(self._sanitize_html_for_reportlab(
                self.t['invoices_and_credit_notes']['check_the_documentation']['text']
            ), self.styles['Normal']),
            Paragraph(self._sanitize_html_for_reportlab(
                self.t['invoices_and_credit_notes']['ask_in_discord']['text']
                .replace("{discord_group_invite_code}", self.discord_group_invite_code)
            ), self.styles['Normal']),
            Paragraph(self._sanitize_html_for_reportlab(
                self.t['invoices_and_credit_notes']['contact_via_email']['text']
                .replace("{email_address}", self.email_address)
            ), self.styles['Normal'])
        ]
        
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
        
        # Add footer with credit explainer - fix <br> tags
        credits_explainer = self._sanitize_html_for_reportlab(self.t['invoices_and_credit_notes']['credits_explainer']['text'])
        # For paragraph flow, convert <br/> to spaces when used in a paragraph
        credits_explainer = re.sub(r'<br\s*/?>', ' ', credits_explainer)
        
        footer_table = Table([[Spacer(self.left_indent, 0),
                             Paragraph(credits_explainer, self.styles['FooterText'])]], 
                             colWidths=[self.left_indent, doc.width-self.left_indent])
        footer_table.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(footer_table)
        
        # Add VAT disclaimer
        elements.append(Spacer(1, 10))
        vat_disclaimer = self._sanitize_html_for_reportlab(self.t['invoices_and_credit_notes']['vat_disclaimer']['text'])
        vat_disclaimer_table = Table([[Spacer(self.left_indent, 0),
                                     Paragraph("* " + vat_disclaimer, self.styles['FooterText'])]], 
                                     colWidths=[self.left_indent, doc.width-self.left_indent])
        vat_disclaimer_table.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(vat_disclaimer_table)
        
        # Add spacer before bottom line
        elements.append(Spacer(1, 20))
        
        # Build PDF with header and footer callbacks
        doc.build(elements, onFirstPage=self._draw_header_footer, onLaterPages=self._draw_header_footer)
        buffer.seek(0)
        return buffer
