// frontend/packages/ui/src/demo_chats/data/example_chats/finance-cash-flow-overview.ts
//
// Example chat: Summarize a recent business finance situation
// Uses synthetic, redacted Revolut Business-style data only. The visible user
// request stays natural-language; connected-account payload details live only in
// the app-skill embed fixture.

import type { ExampleChat } from "../../types";

export const financeCashFlowOverviewChat: ExampleChat = {
  chat_id: "example-finance-cash-flow-overview",
  slug: "finance-cash-flow-overview",
  title: "example_chats.finance_cash_flow_overview.title",
  summary: "example_chats.finance_cash_flow_overview.summary",
  icon: "finance",
  category: "finance",
  keywords: ["finance", "cash flow", "business account", "Revolut Business", "expenses", "income"],
  follow_up_suggestions: [
    "example_chats.finance_cash_flow_overview.follow_up_1",
    "example_chats.finance_cash_flow_overview.follow_up_2",
    "example_chats.finance_cash_flow_overview.follow_up_3",
    "example_chats.finance_cash_flow_overview.follow_up_4",
    "example_chats.finance_cash_flow_overview.follow_up_5",
    "example_chats.finance_cash_flow_overview.follow_up_6",
  ],
  messages: [
    {
      id: "07136074-df11-498e-a539-231481c176d6",
      role: "user",
      content: "example_chats.finance_cash_flow_overview.message_1",
      created_at: 1784657150,
    },
    {
      id: "ba4e92cb-7a1e-53dc-96cd-43cb1e790f4f",
      role: "assistant",
      content: "example_chats.finance_cash_flow_overview.message_2",
      created_at: 1784657170,
      user_message_id: "07136074-df11-498e-a539-231481c176d6",
      category: "finance",
      model_name: "Gemini 3 Flash",
    },
  ],
  embeds: [
    {
      embed_id: "cdffac4e-8176-40f0-a286-e0b98fff36f6",
      type: "app_skill_use",
      content: `app_id: finance
skill_id: check_accounts
status: finished
provider: Revolut Business
period: monthly
account_count: 2
transaction_count: 8
summary: Revenue was steady across the last three months, expenses stayed below income, and the business ended the period with positive net cash flow.
overview_accounts[2]{account_ref,source_ref,display_label,currency,balance,balance_as_of}:
  operating_eur,revolut_business:connected-account,Operating EUR,EUR,18342.58,2026-07-21
  reserve_eur,revolut_business:connected-account,Reserve EUR,EUR,12500.00,2026-07-21
overview_transactions[8]{transaction_ref,account_ref,source_ref,posted_at,amount,currency,direction,category,counterparty_placeholder,state}:
  rb-tx-001,operating_eur,revolut_business:connected-account,2026-05-03,8400.00,EUR,income,revenue,[PAYER_REVENUE_001],completed
  rb-tx-002,operating_eur,revolut_business:connected-account,2026-05-12,-1180.45,EUR,expense,software,[MERCHANT_SOFTWARE_001],completed
  rb-tx-003,operating_eur,revolut_business:connected-account,2026-05-28,-620.00,EUR,expense,contractors,[PAYEE_CONTRACTORS_001],completed
  rb-tx-004,operating_eur,revolut_business:connected-account,2026-06-04,7900.00,EUR,income,revenue,[PAYER_REVENUE_002],completed
  rb-tx-005,operating_eur,revolut_business:connected-account,2026-06-18,-940.20,EUR,expense,marketing,[MERCHANT_MARKETING_001],completed
  rb-tx-006,reserve_eur,revolut_business:connected-account,2026-06-30,1500.00,EUR,income,transfer,[PAYER_TRANSFER_001],completed
  rb-tx-007,operating_eur,revolut_business:connected-account,2026-07-05,8200.00,EUR,income,revenue,[PAYER_REVENUE_003],completed
  rb-tx-008,operating_eur,revolut_business:connected-account,2026-07-16,-1388.77,EUR,expense,travel,[MERCHANT_TRAVEL_001],completed
overview_summaries_period: monthly
overview_summaries_income_total: 26000.00
overview_summaries_expense_total: 4129.42
overview_summaries_net_total: 21870.58
overview_summaries_time_series[3]{bucket,income,expense,net,transaction_count}:
  2026-05,8400.00,1800.45,6599.55,3
  2026-06,9400.00,940.20,8459.80,3
  2026-07,8200.00,1388.77,6811.23,2
overview_filter_options_accounts: operating_eur|reserve_eur
overview_filter_options_sources: revolut_business:connected-account
overview_filter_options_categories: contractors|marketing|revenue|software|transfer|travel
overview_filter_options_directions: expense|income
overview_filter_options_states: completed
overview_filter_options_placeholders: [MERCHANT_MARKETING_001]|[MERCHANT_SOFTWARE_001]|[MERCHANT_TRAVEL_001]|[PAYEE_CONTRACTORS_001]|[PAYER_REVENUE_001]|[PAYER_REVENUE_002]|[PAYER_REVENUE_003]|[PAYER_TRANSFER_001]`,
      parent_embed_id: null,
      embed_ids: null,
      pii_mappings: [
        { placeholder: "[PAYER_REVENUE_001]", original: "Example Studio GmbH", type: "COUNTERPARTY" },
        { placeholder: "[MERCHANT_SOFTWARE_001]", original: "Example SaaS Suite", type: "COUNTERPARTY" },
        { placeholder: "[PAYEE_CONTRACTORS_001]", original: "Example Freelance Partner", type: "COUNTERPARTY" },
        { placeholder: "[PAYER_REVENUE_002]", original: "Example Agency Client", type: "COUNTERPARTY" },
        { placeholder: "[MERCHANT_MARKETING_001]", original: "Example Ads Platform", type: "COUNTERPARTY" },
        { placeholder: "[PAYER_TRANSFER_001]", original: "Example Reserve Transfer", type: "COUNTERPARTY" },
        { placeholder: "[PAYER_REVENUE_003]", original: "Example Retainer Client", type: "COUNTERPARTY" },
        { placeholder: "[MERCHANT_TRAVEL_001]", original: "Example Travel Provider", type: "COUNTERPARTY" },
      ],
    },
  ],
  metadata: {
    featured: true,
    order: 116,
    app_skill_examples: ["finance.check_accounts"],
  },
};
