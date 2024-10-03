# Manual process for creating the jobcenter EKS report

1. create folder structure in dropbox:
   1. '/Abschließende_EKS'
   2. '/Abschließende_EKS/A_Betriebseinnahmen'
   3. '/Abschließende_EKS/B_Betriebsausgaben'
   4. sub folders in both A_Betriebseinnahmen and B_Betriebsausgaben for every month ('10/2023','11/2023',...)
2. check EKS structure and what income and expense categories they have
3. for every category (example 'B1_Wareneinkauf')
   1. filter Akaunting 'invoices', 'bills' and 'transactions' for the matching time frame and category (and have 'transfers' open)
   2. add the total of the category from 'transactions' to the corresponding month field in the online EKS
   3. go over every 'invoice' or 'bill' in that category/timeframe, get all pdf attachments from both the 'invoice/bill' and the connected 'transaction' and copy them over to the matching month and sub category (example: 'B14_Sonstige_Betriebs­ausgaben_c_Neben­kosten_des_Geldverkehrs') folder in dropbox - and also copy them in the main folder with a number that is counting up
   4. don't forget to check 'transfers', for transfers that are also connected to a payment - in that case also attach the pdf attachment of the transfer as proof
   5. create one PDF that contains all the pdf attachments from the 'invoices', 'bills', 'transactions', 'transfers' in the right order (ideally including seperate pages between the documents, to clearly seperate between purchases/sells)
   6. attach huge pdf attachment(s) to online EKS for jobcenter and make sure they are smaller then 9MB (else seperate into multiple files)
4. submit online EKS