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
        self.font_path = os.path.join(os.path.dirname(__file__), "fonts", "LexendDeca-Regular.ttf")
        pdfmetrics.registerFont(TTFont('LexendDeca', self.font_path))
        self.styles = getSampleStyleSheet()
        
        # Modify existing styles
        self.styles['Normal'].fontName = 'LexendDeca'
        self.styles['Normal'].fontSize = 10
        
        # Modify Heading1 instead of adding it
        self.styles['Heading1'].fontName = 'LexendDeca'
        self.styles['Heading1'].fontSize = 20
        
        # Modify or add Heading2
        if 'Heading2' in self.styles:
            self.styles['Heading2'].fontName = 'LexendDeca'
            self.styles['Heading2'].fontSize = 27
            self.styles['Heading2'].alignment = 2  # Right align
        else:
            self.styles.add(ParagraphStyle(name='Heading2', fontName='LexendDeca', fontSize=27, alignment=2))
        
        # Add styles that don't already exist
        self.styles.add(ParagraphStyle(name='Bold', fontName='LexendDeca', fontSize=10, fontWeight='bold'))
        self.styles.add(ParagraphStyle(name='ColorLinks', fontName='LexendDeca', fontSize=10, textColor=colors.HexColor("#7D74FF")))
        self.styles.add(ParagraphStyle(name='FooterText', fontName='LexendDeca', fontSize=10, textColor=colors.HexColor("#848484")))
        
        # Define colors
        self.top_line_color = colors.HexColor("#5951D0")
        self.bottom_line_color = colors.HexColor("#7D74FF")
        self.separator_color = colors.HexColor("#5951D0")
        self.open_color = colors.HexColor("#4867CD")
        
        # Define URLs
        self.contact_url = "https://openmates.org/contact"
        self.terms_url = "https://openmates.org/terms"
        self.privacy_url = "https://openmates.org/privacy"

    def generate_invoice(self, invoice_data):
        buffer = io.BytesIO()
        
        # Use the whole page width and adjust margins
        doc = SimpleDocTemplate(
            buffer, 
            pagesize=A4,
            leftMargin=36,
            rightMargin=36,
            topMargin=36,
            bottomMargin=36
        )
        
        elements = []
        
        # Add colored line at the top
        elements.append(ColoredLine(doc.width + 72, 9, self.top_line_color))
        elements.append(Spacer(1, 20))
        
        # Create header with Invoice and OpenMates side by side
        invoice_text = Paragraph("Invoice", self.styles['Heading1'])
        
        # Create a custom paragraph with two differently colored parts for "OpenMates"
        open_text = '<font color="#4867CD">Open</font><font color="black">Mates</font>'
        openmates_text = Paragraph(open_text, self.styles['Heading2'])
        
        header_table = Table([[invoice_text, openmates_text]], colWidths=[doc.width/2, doc.width/2])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP')
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 24))
        
        # Add invoice details with proper alignment
        invoice_data_table = [
            [Paragraph("Invoice number:", self.styles['Normal']), Paragraph(invoice_data['invoice_number'], self.styles['Normal'])],
            [Paragraph("Date of issue:", self.styles['Normal']), Paragraph(invoice_data['date_of_issue'], self.styles['Normal'])],
            [Paragraph("Date due:", self.styles['Normal']), Paragraph(invoice_data['date_due'], self.styles['Normal'])]
        ]
        
        invoice_table = Table(invoice_data_table, colWidths=[100, 200])
        invoice_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')
        ]))
        elements.append(invoice_table)
        elements.append(Spacer(1, 24))
        
        # Create three-column layout: sender, receiver, and usage info
        sender_details = f'<b>OpenMates</b><br/>Name Nachname<br/>Mustermann Str. 14<br/>12344 Frankfurt<br/>Deutschland<br/>support@openmates.org<br/>VAT: DE9281313'
        sender_paragraph = Paragraph(sender_details, self.styles['Normal'])
        
        receiver_details = f'<b>Bill to:</b><br/>{invoice_data["receiver_name"]}<br/>{invoice_data["receiver_address"]}<br/>{invoice_data["receiver_city"]}<br/>{invoice_data["receiver_country"]}<br/>{invoice_data["receiver_email"]}<br/>VAT: {invoice_data["receiver_vat"]}'
        receiver_paragraph = Paragraph(receiver_details, self.styles['Normal'])
        
        usage_title = Paragraph("<b>View usage:</b>", self.styles['Normal'])
        usage_url = Paragraph(invoice_data['qr_code_url'], self.styles['Normal'])
        
        # Generate QR code
        qr_code = QrCodeWidget(invoice_data['qr_code_url'])
        bounds = qr_code.getBounds()
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        d = Drawing(70, 70, transform=[70./width, 0, 0, 70./height, 0, 0])
        d.add(qr_code)
        
        # Create a table for the usage column
        usage_elements = [[usage_title], [usage_url], [d]]
        usage_table = Table(usage_elements)
        
        # Combine the three columns
        info_table = Table([
            [sender_paragraph, receiver_paragraph, usage_table]
        ], colWidths=[doc.width/3, doc.width/3, doc.width/3])
        
        info_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'LEFT'),
            ('ALIGN', (2, 0), (2, 0), 'LEFT'),
        ]))
        elements.append(info_table)
        
        # Add separator line
        elements.append(Spacer(1, 24))
        elements.append(ColoredLine(doc.width, 1, self.separator_color))
        elements.append(Spacer(1, 24))
        
        # Add item details with proper styling
        item_data = [
            ["Description", "Quantity", "Unit price\n(excl. tax)", "Total\n(excl. tax)"],
            [f"{invoice_data['credits']} credits", "1x", f"€{invoice_data['unit_price']:.2f}", f"€{invoice_data['total_price']:.2f}"]
        ]
        table = Table(item_data, colWidths=[doc.width*0.4, doc.width*0.2, doc.width*0.2, doc.width*0.2])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.top_line_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
            ('ALIGN', (2, 0), (3, -1), 'CENTER'),  # Center align Unit price and Total columns
            ('FONTNAME', (0, 0), (-1, -1), 'LexendDeca'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(table)
        
        # Add separator line before total
        elements.append(Spacer(1, 12))
        elements.append(ColoredLine(doc.width, 1, self.separator_color))
        elements.append(Spacer(1, 12))
        
        # Add payment details
        elements.append(Paragraph(f"Paid with: {invoice_data['card_name']} card ending in {invoice_data['card_last4']}", self.styles['Normal']))
        
        # Add separator line after total
        elements.append(Spacer(1, 12))
        elements.append(ColoredLine(doc.width, 1, self.separator_color))
        elements.append(Spacer(1, 24))
        
        # Add contact information with colored links
        contact_text = f"If you have any questions, contact us at <a href='{self.contact_url}' color='#7D74FF'>openmates.org/contact</a> or read our <a href='{self.terms_url}' color='#7D74FF'>terms</a> and <a href='{self.privacy_url}' color='#7D74FF'>privacy policy</a>."
        elements.append(Paragraph(contact_text, self.styles['Normal']))
        
        # Add footer
        elements.append(Spacer(1, 24))
        footer_text = "Credits on OpenMates are used to chat with your digital team mates and to use apps on OpenMates. Credits cannot be payed out and a refund is only possible within the first 14 days of purchase, and only for the remaining credits in your user account."
        elements.append(Paragraph(footer_text, self.styles['FooterText']))
        
        # Add spacer before bottom line
        elements.append(Spacer(1, 20))
        
        # Add colored line at the bottom
        elements.append(ColoredLine(doc.width + 72, 9, self.bottom_line_color))
        
        # Build PDF
        doc.build(elements)
        buffer.seek(0)
        return buffer
