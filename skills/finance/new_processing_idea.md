# New approach

- import_bank_transactions.py:
  - if new transaction is marked as completed, import transaction to sevdesk
  - if new transaction is marked as reversed, find transaction in sevdesk and remove it (and attached invoices if there are any)

- process_accounting_transactions.py
  - search for transactions which have been added 2 days ago or more
  - (?) send transaction name and purpose to LLM to try to extract seller or customer name for better finding invoice (better only do if multiple vouchers are found that could match with transaction)
  - 2 days after the transaction is completed:
    - if not on list of companies who never send invoice pdfs via email (exclude amazon for example):
      - search in email inbox for invoice pdf (pdf files with "invoice" or "rechnung" in their name or if email subject contains "invoice" or "rechnung" and has a pdf file attached. If multiple pdf files attached, use ocr processing to find the right invoice file)
    - search in dropbox for invoice pdf via ocr (date, amount)
      - if multiple results found, use LLM and GPT4 vision to identify if any of them matches transaction
  - 7 days after the transaction is completed:
    - repeat the same steps
    - if no invoice found, ask via chatbot to upload invoice
  - if pdf found:
    - process with LLLM and GPT4 vision (including ocr text for better accuracy) and send voucher to accounting
    - once voucher is added, search for related transactions
  
## how to process edge cases?
- multiple invoices paid in one transaction
- multiple transactions with same value (-/+) connected to one invoice (when paying via paypal)