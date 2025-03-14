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
import io
import re
import datetime
import locale
from babel.dates import format_date

from app.services.translations import TranslationService
from app.services.email.config_loader import load_shared_urls
from app.services.pdf.invoice import InvoiceTemplateService as PDFInvoiceTemplateService


class InvoiceTemplateService(PDFInvoiceTemplateService):
    """
    Legacy wrapper to maintain backward compatibility.
    This class extends PDFInvoiceTemplateService to ensure all existing code
    that uses InvoiceTemplateService continues to work.
    """
    pass
