import os
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
        # Register both regular and bold fonts
        self.regular_font_path = os.path.join(os.path.dirname(__file__), "fonts", "LexendDeca-Regular.ttf")
        self.bold_font_path = os.path.join(os.path.dirname(__file__), "fonts", "LexendDeca-Bold.ttf")
        
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
        self.contact_url = "https://openmates.org/contact"
        self.terms_url = "https://openmates.org/terms"
        self.privacy_url = "https://openmates.org/privacy"
        
        # Define line height for top and bottom bars
        self.line_height = 9
        
        # Add a small left indent to align elements properly
        self.left_indent = 10

    def _draw_header_footer(self, canvas, doc):
        """Draw the colored bars at the top and bottom of the page"""
        width, height = A4
        
        # Draw top line at the absolute top of the page
        canvas.setFillColor(self.top_line_color)
        canvas.rect(0, height - self.line_height, width, self.line_height, fill=1, stroke=0)
        
        # Draw bottom line at the absolute bottom of the page
        canvas.setFillColor(self.bottom_line_color)
        canvas.rect(0, 0, width, self.line_height, fill=1, stroke=0)
        
        # Add German disclaimer text just above the bottom line
        # Use font size 10 to match other text and increase vertical spacing from bottom line
        canvas.setFont('LexendDeca', 10)
        canvas.setFillColor(colors.HexColor("#848484"))  # Same gray color as FooterText
        canvas.drawString(40, self.line_height + 25, "Diese Rechnung ist eine Übersetzung der originalen englischen Rechnung.")
        canvas.drawString(40, self.line_height + 13, "Die englische Version bleibt das rechtlich bindende Dokument für steuerliche Zwecke.")

    def generate_invoice(self, invoice_data):
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
        invoice_text = Paragraph("Invoice", self.styles['Heading1'])
        
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
        invoice_data_rows = [
            [Paragraph("Invoice number:", self.styles['Normal']), Paragraph(invoice_data['invoice_number'], self.styles['Normal'])],
            [Paragraph("Date of issue:", self.styles['Normal']), Paragraph(invoice_data['date_of_issue'], self.styles['Normal'])],
            [Paragraph("Date due:", self.styles['Normal']), Paragraph(invoice_data['date_due'], self.styles['Normal'])]
        ]
        
        # Direct approach without nested tables to fix alignment
        invoice_table = Table([
            [Spacer(self.left_indent, 0), Paragraph("Invoice number:", self.styles['Normal']), Paragraph(invoice_data['invoice_number'], self.styles['Normal'])],
            [Spacer(self.left_indent, 0), Paragraph("Date of issue:", self.styles['Normal']), Paragraph(invoice_data['date_of_issue'], self.styles['Normal'])],
            [Spacer(self.left_indent, 0), Paragraph("Date due:", self.styles['Normal']), Paragraph(invoice_data['date_due'], self.styles['Normal'])]
        ], colWidths=[self.left_indent, 100, doc.width-self.left_indent-100])
        
        invoice_table.setStyle(TableStyle([
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('ALIGN', (2, 0), (2, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(invoice_table)
        elements.append(Spacer(1, 24))
        
        # Create three-column layout without extra padding
        sender_title = Paragraph("<b>OpenMates</b>", self.styles['Bold'])
        sender_details = Paragraph("Name Nachname<br/>Mustermann Str. 14<br/>12344 Frankfurt<br/>Deutschland<br/>support@openmates.org<br/>VAT: DE9281313", self.styles['Normal'])
        
        bill_to_title = Paragraph("<b>Bill to:</b>", self.styles['Bold'])
        receiver_details = Paragraph(f"{invoice_data['receiver_name']}<br/>{invoice_data['receiver_address']}<br/>{invoice_data['receiver_city']}<br/>{invoice_data['receiver_country']}<br/>{invoice_data['receiver_email']}<br/>VAT: {invoice_data['receiver_vat']}", self.styles['Normal'])
        
        usage_title = Paragraph("<b>View usage:</b>", self.styles['Bold'])
        
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
            Paragraph("<b>Description</b>", self.styles['Bold']),
            Paragraph("<b>Quantity</b>", self.styles['Bold']),
            Paragraph("<b>Unit price<br/>(excl. tax)</b>", self.styles['Bold']),
            Paragraph("<b>Total<br/>(excl. tax)</b>", self.styles['Bold'])
        ]
        
        data_row = [
            Paragraph(f"{invoice_data['credits']} credits", self.styles['Normal']),
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
            [Paragraph("Total (excl. VAT)", self.styles['Normal']), 
             Paragraph(f"€{invoice_data['total_price']:.2f}", self.styles['Normal'])],
            [Paragraph("VAT (0% *)", self.styles['Normal']), 
             Paragraph("€0.00", self.styles['Normal'])],
            [Paragraph("<b>Total paid (incl. VAT)</b>", self.styles['Bold']), 
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
        
        # Add payment details - this is our reference position
        # We will add left indent here too for consistency with paragraph style
        payment_table = Table([[Spacer(self.left_indent, 0), 
                              Paragraph(f"Paid with:<br/>{invoice_data['card_name']} card ending in {invoice_data['card_last4']}", self.styles['Normal'])]], 
                              colWidths=[self.left_indent, doc.width-self.left_indent])
        payment_table.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(payment_table)
        
        # Add contact information with colored links - keep consistent indentation
        contact_table = Table([[Spacer(self.left_indent, 0),
                              Paragraph(f"If you have any questions, contact us at <a href='{self.contact_url}' color='#7D74FF'>openmates.org/contact</a> or read our <a href='{self.terms_url}' color='#7D74FF'>terms</a> and <a href='{self.privacy_url}' color='#7D74FF'>privacy policy</a>.", self.styles['Normal'])]], 
                              colWidths=[self.left_indent, doc.width-self.left_indent])
        contact_table.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(contact_table)
        
        # Add footer with same indentation
        elements.append(Spacer(1, 24))
        footer_table = Table([[Spacer(self.left_indent, 0),
                             Paragraph("Credits on OpenMates are used to chat with your digital team mates and to use apps on OpenMates. Credits cannot be payed out and a refund is only possible within the first 14 days of purchase, and only for the remaining credits in your user account.", self.styles['FooterText'])]], 
                             colWidths=[self.left_indent, doc.width-self.left_indent])
        footer_table.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(footer_table)
        
        # Add spacer before bottom line
        elements.append(Spacer(1, 20))
        
        # Build PDF with header and footer callbacks
        doc.build(elements, onFirstPage=self._draw_header_footer, onLaterPages=self._draw_header_footer)
        buffer.seek(0)
        return buffer
