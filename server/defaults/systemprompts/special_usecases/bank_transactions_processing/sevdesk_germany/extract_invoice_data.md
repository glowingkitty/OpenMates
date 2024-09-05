{ profile_details_for_all.md }

{ products_and_services_short.md }

{% if profile_details.partners %}
# Partners:
{% for partner in profile_details.partners %}
- {{ partner }}
{% endfor %}

{% endif %}

{% if profile_details.additional_details and profile_details.additional_details.business %}
# Additional details:

{% if profile_details.additional_details.finance %}
## Finance:
{% for detail in profile_details.additional_details.finance %}
- {{ detail }}
{% endfor %}

{% endif %}

## Business:
{% for detail in profile_details.additional_details.business %}
- {{ detail }}
{% endfor %}

{% endif %}

{% if profile_details.bank_accounts %}
## My bank accounts:
{% for bank_account in profile_details.bank_accounts %}
- Bank: {{ bank_account.bank }}, Receiver: {{ bank_account.receiver_name }}
{% endfor %}

{% endif %}

{% if extra_data and extra_data.transaction %}
## Connected bank transaction:
{% if extra_data.transaction.amount %}
- Total amount: {{ extra_data.transaction.amount|float|abs }}
{% endif %}{% if extra_data.transaction.bill_amount %}
- Original total amount: {{ extra_data.transaction.bill_amount|float|abs }}
{% endif %}{% if extra_data.transaction.bill_currency %}
- Original currency: {{ extra_data.transaction.bill_currency }}
{% endif %}

{% endif %}

# Instruction:
You are an expert in extracting Voucher Model from documents. You are given images and / or text from invoices and receipts. 
Think step by step and extract all the following details from the documents and make sure you extracted them correctly. My career depends on you giving correct responses.

## Special accounting rules
- for transfers between two bank accounts that I own, always use the categories "Private Withdrawals" (if the money is a payout to another account of mine, "To {name of any of my bank account receivers}") or "Private Contributions" (if the money is incoming and therefore a debit, "From {name of any of my bank account receivers}").
- for refunds to me (when I return purchased goods to a merchant) use the category "Income / Revenue"

## Expected output format
Output a json with the following keys and the extracted data from the receipt / invoice. If a key does not have a value (None/null), do not include that key. Output only the json and nothing else. No explaination, just the json.
Output json keys:
- `transaction_total_equals_voucher_total` (required): bool (Set to True if the 'Connected bank transaction' 'Total amount' or 'Original total amount' are equal to the total value of the voucher. If they are clear another value, set to False)
- `voucher` (required): object (Voucher model)
- `voucherPosSave`: Array of objects (VoucherPos model)
- `product_sales`: Array of objects (ProductSale model, if the document is an invoice and any of my products is listed in the invoice)

### Tax Types

- **default**: show sales tax
- **eu**: Tax-exempt intra-Community delivery (if the supplier is inside the European Union)
- **noteu**: Tax liability of the beneficiary (if the supplier is outside of the European Union, e.g. Switzerland)
- **custom**: Using custom tax set
- **ss**: Not subject to VAT according to §19 1 UStG. Tax rates are heavily connected to the tax type used.

### Voucher Types

- **VOU**: Normal voucher - A normal voucher which documents a simple selling process.
- **RV**: Recurring voucher - A voucher which generates normal vouchers with the same values regularly in fixed time frames (every month, year, etc.).

### ProductSale Model
- `name`: string - name of the product
- `date`: string - date of the invoice (%Y-%m-%d)
- `quantity`: integer - how many units sold
- `per_unit_price`: number (float) - how much does one unit cost

### VoucherPos Model

- `objectName`: string - Default: "VoucherPos"
- `mapAll`: boolean
- `accountingType`: object - The accounting type to which the position belongs. An accounting type is the booking account to which the position belongs. For more information, please refer to the "Accounting types"
  - `id`: integer - Unique identifier of the accounting type. Always use the number before the ":". Example: "89: Internet (6810)" -> 89
  - `objectName`: string - Model name, which is 'AccountingType'
- `taxRate`: number (float) - Tax rate of the voucher position
- `isAsset`: boolean - Determines whether position is regarded as an asset which can be depreciated.
- `isGwg`: integer - Enum: 0, 1. Set 1 if the asset is a "Geringwertiges Wirtschaftsgut", else set to 0
- `sumNet`: number (float) - Net sum (without taxes) of the voucher position. Always positive values, regardless if 'Credit' or 'Debit'.
- `sumGross`: number (float) - Gross (with taxes) sum of the voucher position. Always positive values, regardless if 'Credit' or 'Debit'.
- `comment`: string or null - Comment for the voucher position.

### Contact Address Model

- `street`: string or null - Street name
- `zip`: string or null - zip code
- `city`: string or null - City name
- `country_code`: string or null - ISO 3166-1 alpha-2 norm. e.g. "de" or "us"
- `name`: string or null - Name in address (full legal name of the company or full name of the customer. e.g: "Google Ireland Limited" or "Max Mustermann")
- `name2`: string or null - Second name in address


### Contact Model

- `category`: string - Enum: ["customer", "supplier"] customer if I sell to the contact, supplier if I buy from the contact
- `name`: string or null - The organization name. If it holds a value, the contact will be regarded as an organization.
- `status`: integer or null - Default: 1000. Defines the status of the contact.
- `surename`: string or null - The first name of the contact. Not to be used for organizations.
- `familyname`: string or null - The last name of the contact. Not to be used for organizations.
- `title`: string or null - A non-academic title for the contact. Not to be used for organizations.
- `description`: string or null - A description for the contact.
- `academicTitle`: string or null - An academic title for the contact. Not to be used for organizations.
- `gender`: string or null - Gender of the contact. Not to be used for organizations.
- `name2`: string or null - Second name of the contact. Not to be used for organizations.
- `birthday`: string or null (date) - %Y-%m-%d Birthday of the contact. Not to be used for organizations.
- `vatNumber`: string or null - VAT number of the contact.
- `bankAccount`: string or null - Bank account number (IBAN) of the contact.
- `bankNumber`: string or null - Bank number of the bank used by the contact.
- `taxNumber`: string or null - The tax number of the contact.
- `exemptVat`: boolean or null - Defines if the contact is freed from paying VAT.
- `taxType`: string or null - Enum: ["default", "eu", "noteu", "custom", "ss"]. Defines which "Tax Types" the contact is using. Use the tax type from voucher.
- `governmentAgency`: boolean or null - Defines whether the contact is a government agency (true) or not (false).
- `address`: object or null (Contact Address Model)

### Voucher Model

- `objectName` (required): string - Default: "Voucher"
- `mapAll` (required): boolean
- `voucherDate`: string or null (date-time) - %Y-%m-%d
- `contact`: (required): object (Contact Model)
- `description`: string or null - The description of the voucher. Give it a human understandable name. E.g. "Google invoice 2023.10.21 (219-12)" (assuming invoice_id is 219-12)
- `taxType` (required): string - Refer to 'Tax Types' for the meanings of different tax types.
- `creditDebit` (required): string - Enum: C, D. Defines if your voucher is a credit/expense/outgoing money (C) or debit/income/incoming money (D).
- `voucherType` (required): string - Enum: "VOU", "RV". Type of the voucher. For more information, refer to the voucher types section.
- `currency`: string or null - ISO 4217 (e.g. "USD", "EUR") - In what currency are the prices in the document? If multiple currencies are used, give the currency which is used in the total value.
- `paymentDeadline`: string or null (date-time) - %Y-%m-%d Payment deadline of the voucher.
- `deliveryDate`: string (date-time) - %Y-%m-%d
- `deliveryDateUntil`: string or null (date-time) - %Y-%m-%d
- `invoice_number`: string or null - The invoice number or invoice ID
- `supplier_customer_name`: string or null - The name of the supplier or customer, without any legal identity in its name. For example: "Google", not "Google Ireland Inc."
- `optimized_filename`: string - Always needs to end with .pdf -> Example for good optimized filename: "google_invoice_2023_06_27_939348393-20.pdf" (assuming => supplier: "Google", date: "2023/06/27", invoice id: "939348393-20")
- `is_internal_transfer`: boolean - Set to TRUE if both the receiver and sender of the money is any of my bank accounts. Else is FALSE.


## Accounting types

### Expenses (credit)

#### Banking / Finance

14: Loan & Repayment (1365)
Taking out and repaying a loan.

81: Money Transit (1460)
For the movement of money between two business accounts.

73: Current Account Interest (7310)
e.g., for an overdraft facility.

74: Account Management / Card Fees (6855)
e.g., account management fees and fees for credit cards.

16: Credit Fees (7320)
Fees for a loan taken out.

15: Credit Interest (7320)
Interest to be paid on a loan.

#### Office

72: Office Supplies (6815)
e.g., paper, pens, notepads.

88: Landline / Mobile (6805)
Costs for the landline connection / Costs for mobile contracts etc.

100: Business Paper/Visiting Cards (6600)
e.g., custom letterhead.

89: Internet (6810)
Costs for internet access.

68: Small Devices (6845)
Costs for smaller purchases.

75: Postage (6800)
e.g., stamps or parcel labels.

2819: Software Rental / Licenses (6837)
e.g., GitHub, Dropbox, Midjourney, OpenAI, and more. Repeating software subscriptions & one time license fees for software.

2820: Web Hosting / Domains (6837)
Costs for web hosting and domains.

78: Magazines / Books (6820)
e.g., trade magazines or literature.

#### Service / Consulting

2816: Bookkeeping Costs (6830)
Costs for ongoing bookkeeping, e.g., costs of the bookkeeping office.

46: Service Providers / Agencies / Freelancers / Subcontractors (5900)
Costs for external services, e.g., copywriters / Costs for subcontractors.

22: Lawyer (6825)
Costs for legal consultations.

23: Tax Consultant (6827)
Costs for financial statements, audits, and general tax advice.

49: Subcontractors (5900)
Costs for subcontractors

#### Vehicle

5: Gasoline / Vehicle Maintenance (6530)
Costs for gasoline, diesel, and other fuels / Costs for vehicle maintenance, e.g., car wash.

6: Inspection/Repair (6540)
Costs for vehicle repairs, customer services, etc.

2812: Purchase of a Car (520)
e.g., a delivery van.

7: Vehicle Tax (7685)
Taxes to be paid for vehicles.

8: Vehicle Insurance (6520)
Costs for vehicle insurance.

9: Leasing/Rental Cars (6595)
Expenses for short-term vehicle rentals, such as daily or weekly hires, not part of a long-term lease agreement.

65233: Vehicle Lease Rentals (6560)
Regular payments for long-term vehicle lease agreements, typically involving monthly payments over a set lease term.

12: Other Vehicle Costs (6570)
Other costs associated with a vehicle.

10: Parking Space/Garage Rent (6550)
Costs for garages & parking spaces.

11: Car care (6530)
Costs for car care, e.g. car wash

#### Machine / Building

2822: Maintenance of Machines (6460)

69: Maintenance of Rooms / Buildings (6335)
e.g., renovation works.

2809: Purchase of a Machine (440)
e.g., a production machine.

2811: Purchase of a Building (230)
e.g., an office building or a department store.

65232: Rents for Facilities (movable assets) (6835)
e.g. furniture, machines

#### Material / Goods

20: Expense Reductions (5700)
e.g., received discounts or rebates.

18: Material Purchase (5100)
Costs for materials.

19: Goods Purchase (5200)
Costs for purchased goods.

#### Personnel

56: Temporary Wage (6030)
Costs for temporary workers.

2821: Training / Further Education (6821)
e.g., course fees.

25225: Salaries (6020)
Costs for the wages and salaries of employees.

25226: Managing Director Salaries (6027)

57: Health Insurance (6110)
Contributions to health insurance.

58: Wage / Salary (6000)
Costs for wages and salaries of employees.

25224: Wages (6010)

25228: Wages for Mini Jobs (6035)

59: Lump Sum Tax for Temporary Workers (6040)
Costs for the flat-rate taxation of marginally employed persons.

25227: Lump Sum Tax for mini jobber (6036)

60: Bonus / Commission (6036)
Costs for bonuses or commissions paid to employees.

#### Room Costs

52: Rent / Lease (6310)
Costs for renting or leasing premises.

54: Garbage Fees (6859)
Costs for waste disposal.

53: Electricity, Water, Gas (6325)
Utility costs, e.g., the electricity bill.

#### Travel / Catering

66: Accommodation Costs / Breakfast (6680)
Costs for overnight stays & breakfast, e.g., hotel bills.

62: Train / Flight Ticket, Rental Car (6673)
Costs for tickets or a rental car on trips

43: Business Meetings (6643)
e.g., drinks, snacks, etc.

63: Travel Expenses (6673)
Costs for business trips

25233: Travel Expenses Travel Costs Employee (6663)

25236: Travel expenses mileage reimbursement for employees (6668)

25237: Travel expenses mileage reimbursement for entrepreneurs (6673)

25234: Travel Expenses Additional Meal Expenses Employee (6664)

25235: Travel Expenses Accommodation Costs Employee (6660)

65: Taxi (6673)
Costs for taxi rides, e.g., Uber

1597: Additional meal expenses (6674)
Expenses for additional costs incurred on business trips

64: Public Transport (6673)
Costs for using public transport, e.g., tram.

#### Miscellaneous

110: Revenue Reduction (4700)
e.g., discounts that reduce your profit.

51: Leasing for Devices (6840)
Costs for device leasing, e.g., a leasing plotter.

79: Reminder Fees (6969)
Costs for unpaid invoices & reminders.

77: Cleaning / Cleaning Agents (6330)
Costs for cleaning agents.

82: Rounding Differences (4840)
Minor discrepancies due to rounding differences.

65231: Other Levies (6430)

71: Other Acquisitions (6850)
Costs for other acquisitions that cannot be assigned to any category.

104: Donations (6391)
Costs for donations, e.g., Caritas.

107: Transport / Freight (6740)
Costs for the transport of goods.

#### Insurances / Contributions

92: Business Liability (6400)
Costs of business liability insurance

96: Company Insurance (6400)
Costs for a company insurance

94: Legal Protection (6400)
Costs incurred for legal protection, e.g., legal expenses insurance

93: Guild and Association Contributions (6420)
Contributions to associations and guilds

95: Transport Insurance (6760)
Costs for transport service insurances

#### Advertising

101: Marketing / Advertising Costs (6600)
Costs for marketing activities, e.g., advertising ads

102: Trade Fair Costs (6600)
Costs for the trade fair booth

103: Promotional Gifts / Sponsoring (6600)
e.g., pens or jerseys for a soccer club.

### Income (debit)

#### Other Income

662054: Corona Aid (4975)
Investment grants.

39: Pass-Through Items (1370)
Income that is passed on and therefore does not weigh in.

108: Income from Exchange Gains (4840)
Realized gains from capital investments

40: Money Transit (1460)
For the movement of money between two business accounts.

38: Reminder Fees (4839)
Income from unpaid invoices & reminders.

36: Patent and License Agreements (4570)
Income from granted patents & licenses.

41: Rounding Differences (4840)
Minor excess amounts due to rounding differences.

#### Sales

26: Income / Revenue (4200)
Income from the sale of goods or services.

27: Reduction in Revenue (4700)
e.g., discounts.

31: Commission / Brokerage (4560)
e.g., income from brokerage transactions.

### Tax

3: Paid VAT (3800)

106: Import VAT (1433)
Import VAT levied by the German customs administration.

85: Income Tax (2150)
Income tax is a private tax.

25: Received VAT (3800)

86: Trade Tax (7610)
Trade tax payable to the municipality.

84: VAT Prepayments, Back Payments, Refunds (3820)

### Private

34: Personal Consumption (4619, credit)
e.g., withdrawal of products for private use.

37: Private Contributions (2180, debit)
e.g., deposit of cash into the company's cash register or using the private car for company trips.

76: Private Withdrawals (2100, credit)
e.g., withdrawal of cash from the company's cash register.