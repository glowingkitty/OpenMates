################

# Default Imports

################
import sys
import os
import re
from pdfrw import PdfReader, PdfWriter, PdfDict

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

# prepare the Attachment for self-employment income (Anlage EKS) for the German Federal Employment Agency (Bundesagentur für Arbeit/Jobcenter)

# https://www.arbeitsagentur.de/datei/anlageeks_ba013054.pdf

def print_pdf_field_names(pdf_path):
    pdf = PdfReader(pdf_path)
    for page in pdf.pages:
        fields = page['/Annots']
        for field in fields:
            if field['/Subtype'] == '/Widget' and field['/T']:
                print(field['/T'][1:-1])


def create_attachment_eks(**kwargs) -> str:
    try:
        add_to_log(module_name="Federal Employment Agency | Germany | Attachment EKS | Create EKS", color="yellow", state="start")
        add_to_log("Filling out the PDF template ...")

        # Load the PDF template
        template_path = os.path.join(os.path.dirname(__file__), 'anlageeks_ba013054_template.pdf')
        template_pdf = PdfReader(template_path)
        annotations = template_pdf.pages[0]['/Annots']

        # Fill out the fields with kwargs
        for annotation in annotations:
            if annotation['/Subtype'] == '/Widget' and annotation['/T']:
                key = annotation['/T'][1:-1]  # Remove parentheses around the key
                if key in kwargs:
                    annotation.update(
                        PdfDict(V='{}'.format(kwargs[key]))
                    )

        # Flatten the PDF and save it
        output_path = os.path.join(os.path.dirname(__file__), 'filled_eks.pdf')
        PdfWriter().write(output_path, template_pdf)

        add_to_log(f"Successfully filled and saved the PDF: {output_path}", state="success")
        return output_path

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to fill out the PDF template", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    print_pdf_field_names(os.path.join(os.path.dirname(__file__), 'templates/anlageeks_ba013054_template.pdf'))
    # Example usage
    # create_attachment_eks(name="John Doe", date="2023-12-08")

