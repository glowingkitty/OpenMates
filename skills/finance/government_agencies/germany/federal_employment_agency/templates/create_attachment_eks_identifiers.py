################

# Default Imports

################
import sys
import os
import re
import signal
from pdfrw import PdfReader, PdfWriter, PdfDict

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################


# Custom exception class
class TimeoutException(Exception):   
    pass

# Custom signal handler
def timeout_handler(signum, frame):  
    # TODO it's an uggly solution, but it's a solution. Don't judge me ;)
    add_to_log("The script timed out after 5 seconds. It probably finished successfully anyway.") 
    raise TimeoutException

# Change the behavior of SIGALRM
signal.signal(signal.SIGALRM, timeout_handler)


def create_attachment_eks_identifiers() -> str:
    try:
        add_to_log(module_name="PDF Processing", color="yellow", state="start")
        add_to_log("Filling out the PDF template ...")
        signal.alarm(5)  # Trigger alarm in 5 seconds

        # Load the PDF template
        template_path = os.path.join(os.path.dirname(__file__), 'anlageeks_ba013054_template.pdf')
        template_pdf = PdfReader(template_path)

        # Fill out the fields with unique identifiers
        for page in template_pdf.pages:
            annotations = page['/Annots']
            for annotation in annotations:
                if annotation['/Subtype'] == '/Widget' and annotation['/T'] and annotation['/FT'] != '/Btn':
                    if '/Ff' in annotation and int(annotation['/Ff']) & 1:
                        continue
                    fieldname = annotation['/T']
                    annotation.update(
                        PdfDict(V='{}'.format(fieldname))
                    )

        # Flatten the PDF and save it
        output_path = os.path.join(os.path.dirname(__file__), 'filled_eks_identifiers.pdf')
        add_to_log(f"Saving the PDF...")
        with open(output_path, 'wb') as output_file:
            writer = PdfWriter()
            writer.write(output_file, template_pdf)

        add_to_log(f"Successfully filled and saved the PDF: {output_path}", state="success")
        return output_path

    except KeyboardInterrupt:
        shutdown()

    except TimeoutException:
        return "Function execution timed out"

    except Exception:
        process_error("Failed to fill out the PDF template", traceback=traceback.format_exc())
        return None

    finally:
        signal.alarm(0)  # Cancel the alarm if function finishes within 5 seconds

    return "Finished processing PDF"


if __name__ == "__main__":
    create_attachment_eks_identifiers()