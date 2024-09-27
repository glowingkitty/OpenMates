
# processing:
# - ask the user for concrete symptoms, for how long they exist, what tests have been done so far,
# what are current vitals (for example from smartwatch), what doctors one visited already, if one has
# an referral, a transfer code, etc.
# - then, search for next available appointment within a week on Jameda
# - if found, check if calendar is connected and free at the time of the appointment
# - if calendar is free at the time, ask user to confirm the appointment
# - if user confirms, calendar will be updated and the user will be informed
# - if no appointment found, continue the same search on doctorlib
# - if no appointment found, an email will be draftet and returned to the user for confirmation
# - then, search for doctors nearby on Google Maps
# - then, for every doctor website will be scraped to find the contact email address or contact form
# - then, if only contact form available, contact form will be filled out and submitted automatically
# - then, for doctors with contact email address, email will be sent to the doctor to ask for an appointment
# - then, user will be informed about the sent emails and filled out contact forms