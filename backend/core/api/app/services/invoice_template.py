import os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
import io

class InvoiceTemplateService:
    def __init__(self):
        self.font_path = os.path.join(os.path.dirname(__file__), "fonts", "LexendDeca-Regular.ttf")
        pdfmetrics.registerFont(TTFont('LexendDeca', self.font_path))
        self.styles = getSampleStyleSheet()
        self.styles.add(ParagraphStyle(name='Normal', fontName='LexendDeca', fontSize=10))
        self.styles.add(ParagraphStyle(name='Heading1', fontName='LexendDeca', fontSize=20))
        self.styles.add(ParagraphStyle(name='Heading2', fontName='LexendDeca', fontSize=27, alignment=2))  # Right align

    def generate_invoice(self, invoice_data):
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        elements = []

        # Add header
        elements.append(Paragraph("Invoice", self.styles['Heading1']))
        elements.append(Spacer(1, 12))
        elements.append(Paragraph("OpenMates", self.styles['Heading2']))

        # Add invoice details
        elements.append(Spacer(1, 24))
        elements.append(Paragraph(f"Invoice number: {invoice_data['invoice_number']}", self.styles['Normal']))
        elements.append(Paragraph(f"Date of issue: {invoice_data['date_of_issue']}", self.styles['Normal']))
        elements.append(Paragraph(f"Date due: {invoice_data['date_due']}", self.styles['Normal']))

        # Add sender and receiver details
        elements.append(Spacer(1, 24))
        sender_details = "OpenMates<br/>Name Nachname<br/>Mustermann Str. 14<br/>12344 Frankfurt<br/>Deutschland<br/>support@openmates.org<br/>VAT: DE9281313"
        receiver_details = f"{invoice_data['receiver_name']}<br/>{invoice_data['receiver_address']}<br/>{invoice_data['receiver_city']}<br/>{invoice_data['receiver_country']}<br/>{invoice_data['receiver_email']}<br/>VAT: {invoice_data['receiver_vat']}"
        elements.append(Table([[Paragraph(sender_details, self.styles['Normal']), Paragraph(receiver_details, self.styles['Normal'])]]))

        # Add QR code
        elements.append(Spacer(1, 24))
        qr_code = QrCodeWidget(invoice_data['qr_code_url'])
        bounds = qr_code.getBounds()
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        d = Drawing(50, 50, transform=[50./width, 0, 0, 50./height, 0, 0])
        d.add(qr_code)
        elements.append(d)

        # Add item details
        elements.append(Spacer(1, 24))
        item_data = [
            ["Description", "Quantity", "Unit price<br/>(excl. tax)", "Total<br/>(excl. tax)"],
            [f"{invoice_data['credits']} credits", "1x", f"€{invoice_data['unit_price']:.2f}", f"€{invoice_data['total_price']:.2f}"]
        ]
        table = Table(item_data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#5951D0")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (2, 1), (3, 1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, -1), 'LexendDeca'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(table)

        # Add payment details
        elements.append(Spacer(1, 24))
        elements.append(Paragraph(f"Paid with: {invoice_data['card_name']} card ending in {invoice_data['card_last4']}", self.styles['Normal']))

        # Add footer
        elements.append(Spacer(1, 24))
        footer_text = "Credits on OpenMates are used to chat with your digital team mates and to use apps on OpenMates. Credits cannot be payed out and a refund is only possible within the first 14 days of purchase, and only for the remaining credits in your user account."
        elements.append(Paragraph(footer_text, self.styles['Normal']))

        # Build PDF
        doc.build(elements)
        buffer.seek(0)
        return buffer
