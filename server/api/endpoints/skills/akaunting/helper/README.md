# Processing
1. Whenever a new Revolut Bank transaction is noticed, add a bank transaction in Akauting, including the transaction statement as a PDF attachment
2. Whenever a new PDF file is noticed in Dropbox, extract invoice/bill data from it, create invoice or bill and link to bank transaction and vendor/customer


# How to handle accounting edge cases

1. A bank transaction value does not match with the value of the invoice, because extra bank fees (exchange fees, payment fees) have been added by the bank
    - we create a seperate bank transaction for the fees, connected to the bill
    - we create a regular bank transaction for the value of the bill and connect it
2. An invoice PDF contains multiple invoices
    - we split the pdf into seperate files (workflow connected to dropbox?)
3. An invoice (hetzner or openai for example) uses 4 digits, but the bank account only 2 digits (rounded up)
    - if invoice includes items total with 2 digits (like OpenAI invoice), use that value and quantity 1 instead of higher quantity and 4 digit value
    - instead of adding seperate items with the 4 digit values, we add one single item with 2 digit value and adapt it so that together with the VAT it matches the total value of the bank transaction (exluding bank transaction fees)
4. An invoice has multiple listed contact companies in multiple countries (example: amazon web services)
    - if one of them is in the same country as our company, use the info from that company
5. An invoice includes items that have been processed in previous bills/invoices (example: amazon web services)
    - include in the prompt for the LLM a list of all items (names and IDs), so they can be matched more easily by the LLM (but make sure to exclude items that have not been used in months)
6. An invoice uses multiple currencies in their calculation (example: amazon web services)
    - use the currency of the connected bank transaction or else default currency of our company/organization
7. An invoice includes a customer/vendor that has been processed before (example: amazon web services)
    - include list of all customers/vendors (names and IDs) in the prompt for the LLM
8. An invoice has multiple pages, but the last one is basically empty
    - make sure its still processed as part of the same invoice document, not seperated into another file or deleted
9. The calculated currency conversion value of a USD bill into EUR does not exactly match the value of the currency conversion of the bank transaction with its exchange rate (example: invoice 2C0232BC-0008 from OpenAI)
    - adapt exchange rate in akauting, so the calculated value matches the bank transaction value (excluding bank transaction fees)
10. There is no bill id, but an Transaction ID on the invoice
    - use transaction ID as bill ID
11. An invoice is paid via stripe or another payment provider and the bank transaction value doesn't match the invoice value, because stripe / payment provider substracts the payment fee from the invoice value
    - create an income bank transaction for the full value of the invoice, with the bank transaction of the reduced income attached
    - create an expense bank transaction for the payment fee, with the value of the invoice minus the actual income = fees, with the bank transaction of the reduced income attached, make sure the invoice is linked either via database entry or description field
12. I made a purchase and received an email with a confirmation, but no invoice, then there is a bank transaction the same day of the email. Then a few days later there is an email with an attached pdf for an 'Auftrag' (but not invoice)
    - for every email it should check for attached PDFs and check if they are an invoice or auftrag pdf - and attach / process it
    - if a new matching invoice pdf comes in via email or dropbox, also add that pdf as attachment
13. I purchased something via PayPal, which then maybe uses Paypal balance, bank transaction or a mix of both for payment
    - get paypal transactions via api and process them just like bank transactions
    - for bank transactions from paypal, create a bank transfer entry from bank account to paypal
14. Items from amazon invoices often have super long names
    - ask llm to seperate into short name and longer description
15. amazon invoices often mention some unknown chinese company name as the seller, but also mention Amazon Services Europe S.a.r.L. as the company responsible for taxes (or amazon url for contact details)
    - if Amazon is on the invoice, use Amazon as the vendor, not the merchant name from amazon
16. Money between a private bank account and a business account is moved
    - use a seperate private bank account in akaunting and treat them as regular transfers, to not inflate income/expense values
17. Aliexpress invoices are a confusing mess and the numbers don't make sense because of rounding differences
    - if aliexpress/alibaba, then use the value of the bank transaction as the value of the bill and ask LLM to summarize the items in the invoice in one position instead of having seperate ones (and calculate NET value based on bank transaction value)
18. Some sellers like HUG Technik shop don't sent invoice PDFs but invoice emails
    - save those emails as PDF and process them as normal
19. In my work email inbox there is an invoice for something I paid with using my personal bank account, not business. Therefore there will never be a match with any bank transaction from my business bank account.
    - always save bills first as draft
    - if after a few days there is still no bank transaction found, ask via chat if it should be kept or if it was paid with a different bank account?
    - if after 2 weeks there is still no bank transaction match, delete the draft (run a script to delete all drafts after 2 weeks, but after informing the user via chat two days before)
20. Invoice shows shipping costs, sometimes as extra item, sometimes after the items. We want to be able to track shipping costs.
    - make sure that for every item there is a category
    - make sure that if the shipping costs are mentioned anywhere, to always add them as a seperate item with the category 'Shipping'
    - if 'Customs & import fees' are mentioned, also add them as seperate item / category
20. Some invoices (example: TeleportHQ/Evo Forge) don't clearly mention the discount value, but instead just adapt the total value of the invoice
    - if the total value of the invoice doesn't match the total of all items combined, add a discount of the difference, up to the point that total matches (consider also how VAT impacts that calculation)
21. Even after calculating the discount in 20., there still might be a rounding error of a few cents, causing the invoice total to not match with the bank transaction value.
    - create a bill with the rounded up value, add a bank transaction for the same value, mark bill as fully paid, but then change the value of the bank transaction to the actual booked bank transaction value (and make sure bill still shows up as fully paid)
22. An invoice has a total value of 0 euro, for whatever reason
    - don't add the invoice and just ignore it
23. An invoice (JLCPCB as example) is in EUR, but the bank transaction is in USD, with a exchange rate that is different and therefore the total of the transaction and the total of the invoice don't match
    - add discount or extra item to the invoice/bill to make the total match the bank transaction value
    - add a note in bill that explains the correction reason


# Additional ideas:
- Revolut processing script: output a list of all transactions that should be created (one bank transaction would be split up into multiple, if fees from Revolut are included or the payment is from a payment processor like Stripe and the value doesn't match with an invoice in that time period)
- both revolut to akaunting and dropbox to akaunting workflows would attempt to find a matching bill/invoice/transaction to complete the entry
- write script that processes all items and checks for multiple entries with nearly the exact same name, which are likely the same and can be merged
