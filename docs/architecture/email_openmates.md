# E-mail OpenMates architecture

> Feature not yet implemented

"E-Mail OpenMates" is deactivated by default, and once turned on generates an email address unique for the user, to which the user can send or forward emails. This will trigger OpenMates to process the email and respond to it.

## Security

Multiple layers of security will be implemented:

1. User specific email address is generated to receive emails from user
2. Always required: User needs to add their sender email address to list of allowed email senders
3. Always required: Email sent to OpenMates must pass SPF + DKIM + DMARC to prevent email spoofing (someone pretending to send from an email address they dont have access to)
4. Always required: every sensitive app skill use and including app settings and memories content requires confirmation in chat in web app
5. Setting, OFF by default: Require user confirmation in chat in web app before OpenMates will process the email.
6. Setting, ON by default: Send response only in web app and not via email - and instead inform via email when request is completed.

## Processing

- email is received via forwardemail.net
- security checks passed
- if user activated confirmation for every email: notification in web app to ask user to confirm processing of email + email response says "please confirm in the chat in the web app: openmates.org/#chatid=uut274ha"
- once manually or auto confirmed: process email and fullfill request (but send notification via web app and email response if an app skill use or including app settings and memories requires web app confirmation)
- if user activated full response via email: completed will be sent via email in addition to showing up in web app. Else (default) only send confirmation via email that request was processed and link to chat.


