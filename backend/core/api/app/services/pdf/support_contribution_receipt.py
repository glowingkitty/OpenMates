import io
import logging
from datetime import datetime
from typing import Dict, Any

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from backend.core.api.app.services.pdf.base import BasePDFTemplateService
from backend.core.api.app.services.pdf.utils import sanitize_html_for_reportlab, format_date_for_locale
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)


class SupportContributionReceiptTemplateService(BasePDFTemplateService):
    def __init__(self, secrets_manager: SecretsManager):
        super().__init__(secrets_manager)

    def generate_receipt(self, receipt_data: Dict[str, Any], lang: str = "en") -> bytes:
        """
        Generate a supporter contribution receipt PDF.

        Expected receipt_data keys:
        - receipt_number (str)
        - date_of_issue (YYYY-MM-DD)
        - receiver_account_id (optional str)
        - receiver_email (optional str, used for guest receipts)
        - description (str)
        - amount_display (str) e.g. "5.00 EUR"
        - sender_* overrides (optional, same keys as invoice template)
        """
        buffer = io.BytesIO()

        self.current_lang = lang
        self.t = self.translation_service.get_translations(lang)

        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=36,
            rightMargin=36,
            topMargin=20 + self.line_height,
            bottomMargin=36 + self.line_height,
        )

        elements = []
        elements.append(Spacer(1, 5))

        title_text = sanitize_html_for_reportlab(self.t["invoices_and_credit_notes"]["invoice"]["text"])
        title = Paragraph(title_text, self.styles["Heading1"])
        open_text = '<font color="#4867CD">Open</font><font color="black">Mates</font>'
        openmates_title = Paragraph(open_text, self.styles["Heading2"])

        header_table = Table([[title, openmates_title]], colWidths=[doc.width * 0.55, doc.width * 0.45])
        header_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (0, 0), "LEFT"),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        elements.append(header_table)
        elements.append(Spacer(1, 18))

        # Basic receipt meta table
        receipt_number_label = sanitize_html_for_reportlab(self.t["invoices_and_credit_notes"]["invoice_number"]["text"])
        date_issue_label = sanitize_html_for_reportlab(self.t["invoices_and_credit_notes"]["date_of_issue"]["text"])

        receipt_table = Table(
            [
                [Paragraph(receipt_number_label, self.styles["Normal"]), Paragraph(receipt_data["receipt_number"], self.styles["Normal"])],
                [
                    Paragraph(date_issue_label, self.styles["Normal"]),
                    Paragraph(format_date_for_locale(receipt_data["date_of_issue"], self.current_lang), self.styles["Normal"]),
                ],
            ],
            colWidths=[doc.width * 0.35, doc.width * 0.65],
        )
        receipt_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        elements.append(receipt_table)
        elements.append(Spacer(1, 18))

        # Sender / receiver block
        sender_addressline1 = receipt_data.get("sender_addressline1", self.sender_addressline1)
        sender_addressline2 = receipt_data.get("sender_addressline2", self.sender_addressline2)
        sender_addressline3 = receipt_data.get("sender_addressline3", self.sender_addressline3)
        sender_country_val = receipt_data.get("sender_country", self.sender_country)
        sender_email_val = receipt_data.get("sender_email", self.sender_email)
        sender_vat_val = receipt_data.get("sender_vat", self.sender_vat)
        translated_sender_country = self._get_translated_country_name(sender_country_val) if sender_country_val else ""

        sender_details_str = (
            f"{sender_addressline1}<br/>{sender_addressline2}<br/>{sender_addressline3}"
            + (f"<br/>{translated_sender_country}" if translated_sender_country else "")
            + (f"<br/>{sender_email_val}" if sender_email_val else "")
            + (f"<br/>{self.t['invoices_and_credit_notes']['vat']['text']}: {sender_vat_val}" if sender_vat_val else "")
        )
        sender_title = Paragraph("<b>OpenMates</b>", self.styles["Bold"])
        sender_details = Paragraph(sender_details_str, self.styles["Normal"])

        receiver_title_text = sanitize_html_for_reportlab(self.t["invoices_and_credit_notes"]["receiver"]["text"])
        receiver_title = Paragraph(f"<b>{receiver_title_text}</b>", self.styles["Bold"])

        receiver_fields = []
        if receipt_data.get("receiver_account_id"):
            receiver_fields.append(f"Account ID: {receipt_data['receiver_account_id']}")
        if receipt_data.get("receiver_email"):
            receiver_fields.append(receipt_data["receiver_email"])

        receiver_details = Paragraph("<br/>".join(receiver_fields), self.styles["Normal"]) if receiver_fields else Paragraph("", self.styles["Normal"])

        parties_table = Table(
            [[sender_title, receiver_title], [sender_details, receiver_details]],
            colWidths=[doc.width * 0.5, doc.width * 0.5],
        )
        parties_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        elements.append(parties_table)
        elements.append(Spacer(1, 18))

        # Line item table
        description = receipt_data.get("description", "Supporter contribution")
        amount_display = receipt_data.get("amount_display", "")

        items_table = Table(
            [
                [Paragraph("<b>Description</b>", self.styles["Bold"]), Paragraph("<b>Amount</b>", self.styles["Bold"])],
                [Paragraph(sanitize_html_for_reportlab(description), self.styles["Normal"]), Paragraph(sanitize_html_for_reportlab(amount_display), self.styles["Normal"])],
            ],
            colWidths=[doc.width * 0.7, doc.width * 0.3],
        )
        items_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        elements.append(items_table)

        def _draw(canvas, doc_obj):
            self._draw_header_footer(canvas, doc_obj)

        doc.build(elements, onFirstPage=_draw, onLaterPages=_draw)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        logger.info(f"Generated support contribution receipt PDF ({len(pdf_bytes)} bytes) for {receipt_data.get('receipt_number')}")
        return pdf_bytes

