import io
import logging
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.barcode.qr import QrCodeWidget
import re

from app.services.pdf.base import BasePDFTemplateService
from app.services.pdf.utils import (sanitize_html_for_reportlab, replace_placeholders_safely,
                                   format_date_for_locale, format_credits)

# Setup loggers
logger = logging.getLogger(__name__)

class InvoiceTemplateService(BasePDFTemplateService):
    def __init__(self, secrets_manager=None):
        from app.utils.secrets_manager import SecretsManager
        if secrets_manager is None:
            secrets_manager = SecretsManager()
        super().__init__(secrets_manager)
    
    def get_translation_disclaimer(self):
        """Get the invoice translation disclaimer text"""
        return self.t["invoices_and_credit_notes"]["this_invoice_is_a_translation"]["text"]
        
    def generate_invoice(self, invoice_data, lang="en", currency="eur"):
        """Generate an invoice PDF with the specified language and currency"""
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
        
        # Create header with Invoice and OpenMates side by side - no extra padding
        invoice_text = Paragraph(sanitize_html_for_reportlab(self.t["invoices_and_credit_notes"]["invoice"]["text"]), self.styles['Heading1'])
        
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
        credits_text = sanitize_html_for_reportlab(
            self.t["invoices_and_credit_notes"]["credits_item"]["text"].replace("{amount}", formatted_credits)
        )
        
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
        
        # Add larger spacer before questions helper
        elements.append(Spacer(1, 40))
        
        # Add questions helper section
        self.build_questions_helper_section(elements, doc)

        # Build PDF with header and footer callbacks
        doc.build(elements, onFirstPage=self._draw_header_footer, onLaterPages=self._draw_header_footer)
        buffer.seek(0)
        return buffer
