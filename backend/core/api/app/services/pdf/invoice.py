import io
import logging
from reportlab.lib.pagesizes import A4

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.barcode.qr import QrCodeWidget
import re

from backend.core.api.app.services.pdf.base import BasePDFTemplateService
from backend.core.api.app.services.pdf.utils import (sanitize_html_for_reportlab,
                                   format_date_for_locale, format_credits)
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Setup loggers
logger = logging.getLogger(__name__)

class InvoiceTemplateService(BasePDFTemplateService):
    def __init__(self, secrets_manager: SecretsManager):
        super().__init__(secrets_manager)
    
    def get_translation_disclaimer(self):
        """Get the invoice translation disclaimer text"""
        return self.t["invoices_and_credit_notes"]["this_invoice_is_a_translation"]["text"]
    
    def _get_click_here_text_for_language(self, lang):
        """
        Get the language-specific "Click here" text for the refund link
        
        Args:
            lang: Language code (e.g., 'en', 'de', 'fr')
            
        Returns:
            Language-specific "Click here" text
        """
        # Map of language codes to their "Click here" translations
        click_here_translations = {
            'en': 'Click here',
            'de': 'Klicke hier',
            'zh': '点击这里',
            'es': 'Haz clic aquí',
            'fr': 'Cliquez ici',
            'ja': 'ここをクリック',
            'pt': 'Clique aqui',
            'ru': 'Нажмите здесь',
            'ko': '여기를 클릭하세요',
            'it': 'Clicca qui',
            'tr': 'Buraya tıklayın',
            'vi': 'Nhấp vào đây',
            'id': 'Klik di sini',
            'pl': 'Kliknij tutaj',
            'nl': 'Klik hier',
            'ar': 'انقر هنا',
            'hi': 'यहाँ क्लिक करें',
            'th': 'คลิกที่นี่',
            'cs': 'Klikněte zde',
            'sv': 'Klicka här'
        }
        # Return the translation for the language, or default to English
        return click_here_translations.get(lang, 'Click here')
        
    def generate_invoice(self, invoice_data, lang="en", currency="eur", document_type: str = "invoice"):
        """
        Generate an invoice or payment confirmation PDF.

        Args:
            invoice_data: Dictionary of invoice fields (invoice_number, dates, credits, etc.)
            lang: Language code for translations (e.g. "en", "de")
            currency: ISO currency code lowercase (e.g. "eur", "usd")
            document_type: "invoice" (default, for Stripe/Revolut) or "payment_confirmation"
                           (for Polar — Polar as MoR issues the official tax invoice separately)
        """
        # Create a buffer for the PDF
        buffer = io.BytesIO()

        # Set the current language for use throughout the template
        self.current_lang = lang

        # Load translations for the specified language
        self.t = self.translation_service.get_translations(lang)

        # Validate and get the credits from invoice data
        credits = self._validate_credits(invoice_data.get('credits', 1000))
        
        # Format the credits for display
        formatted_credits = format_credits(credits)
        
        # Get the unit price for these credits
        unit_price = self._get_price_for_credits(credits, currency)
        
        # Set the unit and total price in the invoice data
        invoice_data['unit_price'] = unit_price
        invoice_data['total_price'] = unit_price  # Since quantity is 1
        
        # Check if language is supported, fall back to English if not
        if not self._is_language_supported(lang):
            # Fall back to English silently
            lang = "en"
        
        # Normalize currency to lowercase
        currency = currency.lower()
        
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
        
        # Create header with document title and OpenMates side by side.
        # For Polar orders: "Payment Confirmation" (Polar as MoR issues the real tax invoice).
        # For all others: "Invoice".
        if document_type == "payment_confirmation":
            heading_text = self.t.get("invoices_and_credit_notes", {}).get("payment_confirmation", {}).get("text", "Payment Confirmation")
        else:
            heading_text = self.t["invoices_and_credit_notes"]["invoice"]["text"]
        invoice_text = Paragraph(sanitize_html_for_reportlab(heading_text), self.styles['Heading1'])
        
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
             Paragraph(format_date_for_locale(invoice_data['date_of_issue'], self.current_lang), self.styles['Normal'])],
            [Spacer(self.left_indent, 0), Paragraph(date_due_text, self.styles['Normal']), 
             Paragraph(format_date_for_locale(invoice_data['date_due'], self.current_lang), self.styles['Normal'])]
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
        
        # Create sender details string, preferring values from invoice_data with fallbacks
        sender_addressline1 = invoice_data.get('sender_addressline1', self.sender_addressline1)
        sender_addressline2 = invoice_data.get('sender_addressline2', self.sender_addressline2)
        sender_addressline3 = invoice_data.get('sender_addressline3', self.sender_addressline3)
        sender_country_val = invoice_data.get('sender_country', self.sender_country)
        translated_sender_country = self._get_translated_country_name(sender_country_val)
        sender_email_val = invoice_data.get('sender_email', self.sender_email)
        sender_vat_val = invoice_data.get('sender_vat', self.sender_vat)
        sender_details_str = (
            f"{sender_addressline1}<br/>{sender_addressline2}<br/>{sender_addressline3}"
            f"<br/>{translated_sender_country}<br/>{sender_email_val}"
            f"<br/>{self.t['invoices_and_credit_notes']['vat']['text']}: {sender_vat_val}"
        )
        
        # Create three-column layout without extra padding
        sender_title = Paragraph("<b>OpenMates</b>", self.styles['Bold'])
        sender_details = Paragraph(sender_details_str, self.styles['Normal'])
        
        receiver_title = Paragraph(f"<b>{self.t['invoices_and_credit_notes']['receiver']['text']}</b>", self.styles['Bold'])
        
        # Get translated receiver country if it exists
        translated_receiver_country = ""
        if invoice_data.get('receiver_country'):
            translated_receiver_country = self._get_translated_country_name(invoice_data['receiver_country'])
        
        # Build receiver details with only non-empty fields
        receiver_fields = []
        
        # Show account ID instead of email for privacy and professionalism
        if invoice_data.get('receiver_account_id'):
            receiver_fields.append(f"Account ID: {invoice_data['receiver_account_id']}")
        
        # For preview/dummy data, show receiver name and address if available
        # TODO: For future "teams" functionality, we would show full name, address, and VAT for business accounts.
        if invoice_data.get('receiver_name'):
            receiver_fields.append(invoice_data['receiver_name'])
            
        if invoice_data.get('receiver_address'):
            receiver_fields.append(invoice_data['receiver_address'])
            
        if invoice_data.get('receiver_city'):
            receiver_fields.append(invoice_data['receiver_city'])
            
        if translated_receiver_country:
            receiver_fields.append(translated_receiver_country)
            
        if invoice_data.get('receiver_vat'):
            receiver_fields.append(f"{self.t['invoices_and_credit_notes']['vat']['text']}: {invoice_data['receiver_vat']}")
        
        # Join all non-empty fields with line breaks
        receiver_details_str = "<br/>".join(receiver_fields) if receiver_fields else ""
        receiver_details = Paragraph(receiver_details_str, self.styles['Normal']) if receiver_details_str else Paragraph("", self.styles['Normal'])
        
        # Create usage section with link and QR code
        usage_title = Paragraph(f"<b>{self.t['invoices_and_credit_notes']['view_usage']['text']}:</b>", self.styles['Bold'])
        
        # Get webapp URL from config and construct usage URL
        webapp_url = self._get_webapp_url()
        url = f"{webapp_url}/#settings/usage"
        
        # Format URL properly with line break while maintaining a single clickable link
        # Find a good spot to split the URL - after the domain
        split_index = url.find('/', 8)  # Find first '/' after http(s)://
        if (split_index != -1):
            formatted_url = f"<a href='{url}'>{url[:split_index+1]}<br/>{url[split_index+1:]}</a>"
        else:
            formatted_url = f"<a href='{url}'>{url}</a>"
            
        usage_url = Paragraph(formatted_url, self.styles['Normal'])
        
        # Generate QR code
        qr_code = QrCodeWidget(url)
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
            ('BOTTOMPADDING', (0, 0), (0, 0), 0),
        ]))
        
        receiver_table = Table([[receiver_title], [receiver_details]])
        receiver_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (0, 0), 0),
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
            ('BOTTOMPADDING', (0, 0), (0, 0), 0),
            # Special negative padding for QR code to force left alignment
            ('LEFTPADDING', (0, 2), (0, 2), -7),
        ]))
        
        # Three-column layout (sender, receiver, and usage sections)
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
            Paragraph(f"<b>{sanitize_html_for_reportlab(self.t['invoices_and_credit_notes']['description']['text'])}</b>", self.styles['Bold']),
            Paragraph(f"<b>{sanitize_html_for_reportlab(self.t['invoices_and_credit_notes']['quantity']['text'])}</b>", self.styles['Bold']),
            Paragraph(f"<b>{sanitize_html_for_reportlab(self.t['invoices_and_credit_notes']['unit_price_no_tax']['text'])}</b>", self.styles['Bold']),
            Paragraph(f"<b>{sanitize_html_for_reportlab(self.t['invoices_and_credit_notes']['total_price_no_tax']['text'])}</b>", self.styles['Bold'])
        ]
        
        # Format the credits text using the translation
        # For gift cards, prefix with "Gift card - " to distinguish from regular credit purchases
        base_credits_text = self.t["invoices_and_credit_notes"]["credits_item"]["text"].replace("{amount}", formatted_credits)
        if invoice_data.get('is_gift_card', False):
            # Prefix with "Gift card - " for gift card purchases
            credits_text = sanitize_html_for_reportlab(f"Gift card - {base_credits_text}")
        else:
            credits_text = sanitize_html_for_reportlab(base_credits_text)
        
        # Get the appropriate currency symbol based on the currency
        currency_symbols = {
            'eur': '€',
            'usd': '$',
            'jpy': '¥',
            # Add more currencies as needed
        }
        currency_symbol = currency_symbols.get(currency.lower(), '€')  # Default to Euro symbol
        
        data_row = [
            Paragraph(credits_text, self.styles['Normal']),
            Paragraph("1x", self.styles['Normal']),
            Paragraph(f"{currency_symbol}{invoice_data['unit_price']:.2f}", self.styles['Normal']),
            Paragraph(f"{currency_symbol}{invoice_data['total_price']:.2f}", self.styles['Normal'])
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
             Paragraph(f"{currency_symbol}{invoice_data['total_price']:.2f}", self.styles['Normal'])],
            [Paragraph(self.t["invoices_and_credit_notes"]["vat_rate"]["text"] + " *", self.styles['Normal']), 
             Paragraph(f"{currency_symbol}0.00", self.styles['Normal'])],
            [Paragraph(f"<b>{self.t['invoices_and_credit_notes']['total_paid']['text']}</b>", self.styles['Bold']), 
             Paragraph(f"<b>{currency_symbol}{invoice_data['total_price']:.2f}</b>", self.styles['Bold'])]
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
        elements.append(Spacer(1, 24))  # Increased from 10 to 24
        
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
        paid_with_text = sanitize_html_for_reportlab(paid_with_text)
        
        try:
            # Create paragraph with error catching
            paid_with_paragraph = Paragraph(paid_with_text, self.styles['Normal'])
            payment_table = Table([[Spacer(self.left_indent, 0), paid_with_paragraph]], 
                                 colWidths=[self.left_indent, doc.width-self.left_indent])
        except Exception:
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
        
        # Add larger spacer before credits explainer
        elements.append(Spacer(1, 40))
        
        # Add footer with credit explainer - fix <br> tags - now in black, not grey
        credits_explainer = sanitize_html_for_reportlab(self.t['invoices_and_credit_notes']['credits_explainer']['text'])
        # For paragraph flow, convert <br/> to spaces when used in a paragraph
        credits_explainer = re.sub(r'<br\s*/?>', ' ', credits_explainer)
        
        footer_table = Table([[Spacer(self.left_indent, 0),
                             Paragraph(credits_explainer, self.styles['Normal'])]], # Changed from 'FooterText' to 'Normal'
                             colWidths=[self.left_indent, doc.width-self.left_indent])
        footer_table.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(footer_table)
        
        # Add VAT disclaimer
        elements.append(Spacer(1, 10))
        vat_disclaimer = sanitize_html_for_reportlab(self.t['invoices_and_credit_notes']['vat_disclaimer']['text'])
        vat_disclaimer_table = Table([[Spacer(self.left_indent, 0),
                                     Paragraph("* " + vat_disclaimer, self.styles['Normal'])]], # Changed from 'FooterText' to 'Normal'
                                     colWidths=[self.left_indent, doc.width-self.left_indent])
        vat_disclaimer_table.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(vat_disclaimer_table)

        # For Polar: add Merchant of Record note explaining that Polar issued the official tax invoice.
        # This is legally required because Polar (not OpenMates) issued the buyer's VAT/tax invoice.
        if document_type == "payment_confirmation":
            polar_mor_note = self.t.get("invoices_and_credit_notes", {}).get("polar_mor_note", {}).get(
                "text",
                "Your official tax invoice was issued by Polar (polar.sh) as Merchant of Record."
            )
            polar_mor_note_sanitized = sanitize_html_for_reportlab(polar_mor_note)
            polar_mor_table = Table([[Spacer(self.left_indent, 0),
                                     Paragraph(polar_mor_note_sanitized, self.styles['Normal'])]],
                                    colWidths=[self.left_indent, doc.width - self.left_indent])
            polar_mor_table.setStyle(TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            elements.append(Spacer(1, 10))
            elements.append(polar_mor_table)

        # Add withdrawal waiver notice (required for EU/German consumer law compliance)
        # This comes BEFORE the refund link
        elements.append(Spacer(1, 10))
        withdrawal_waiver_text = sanitize_html_for_reportlab(self.t['invoices_and_credit_notes']['withdrawal_waiver_notice']['text'])
        withdrawal_waiver_table = Table([[Spacer(self.left_indent, 0),
                                     Paragraph(withdrawal_waiver_text, self.styles['Normal'])]],
                                     colWidths=[self.left_indent, doc.width-self.left_indent])
        withdrawal_waiver_table.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(withdrawal_waiver_table)

        # Add refund link notice (if refund_link is provided)
        # This comes AFTER the withdrawal waiver notice
        if invoice_data.get('refund_link'):
            elements.append(Spacer(1, 10))
            refund_text = self.t['invoices_and_credit_notes']['click_here_for_refund']['text']
            # Get the language-specific "Click here" text from translations
            # We need to extract what text should be in the link based on the language
            # For now, we'll use a simple approach: get "Click here" translation
            # The placeholder {click_here_link} will be replaced with a colored link
            # The link color matches the support email color (#4867CD)
            click_here_text = self._get_click_here_text_for_language(self.current_lang)
            refund_link_html = f"<a href='{invoice_data['refund_link']}' color='#4867CD'>{click_here_text}</a>"
            # Replace the {click_here_link} placeholder with the colored link
            refund_text = refund_text.replace('{click_here_link}', refund_link_html)
            refund_text = sanitize_html_for_reportlab(refund_text)
            # Use Normal style (black text) - the link inside will be colored automatically
            refund_table = Table([[Spacer(self.left_indent, 0),
                                 Paragraph(refund_text, self.styles['Normal'])]],
                                 colWidths=[self.left_indent, doc.width-self.left_indent])
            refund_table.setStyle(TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            elements.append(refund_table)

        # Add subscription management link (if customer_portal_url is provided)
        if invoice_data.get('customer_portal_url'):
            elements.append(Spacer(1, 10))
            manage_label = sanitize_html_for_reportlab(self.t["billing"]["manage_subscription"]["text"])
            manage_info = sanitize_html_for_reportlab(self.t["settings"]["support"]["subscription_management_info"]["text"])
            
            manage_text = f"<b>{manage_label}:</b> {manage_info}"
            manage_table = Table([[Spacer(self.left_indent, 0),
                                 Paragraph(manage_text, self.styles['Normal'])]],
                                 colWidths=[self.left_indent, doc.width-self.left_indent])
            manage_table.setStyle(TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            elements.append(manage_table)
            
            elements.append(Spacer(1, 5))
            portal_link_html = f"<a href='{invoice_data['customer_portal_url']}' color='#4867CD'>{invoice_data['customer_portal_url']}</a>"
            portal_link_table = Table([[Spacer(self.left_indent, 0),
                                      Paragraph(portal_link_html, self.styles['Normal'])]],
                                      colWidths=[self.left_indent, doc.width-self.left_indent])
            portal_link_table.setStyle(TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            elements.append(portal_link_table)
        
        # Add larger spacer before questions helper
        elements.append(Spacer(1, 40))
        
        # Add questions helper section
        self.build_questions_helper_section(elements, doc)

        # Build PDF with header and footer callbacks
        doc.build(elements, onFirstPage=self._draw_header_footer, onLaterPages=self._draw_header_footer)
        buffer.seek(0)
        return buffer
