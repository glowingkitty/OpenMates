import { investorData, warningData, emptyData, errorData } from './BusinessInvestorSearchEmbedPreview.preview';
const props = { data: { decodedContent: investorData }, onClose: () => {} };
export default props;
export const variants = {
  warning: { ...props, data: { decodedContent: warningData } },
  empty: { ...props, data: { decodedContent: emptyData } },
  error: { ...props, data: { decodedContent: errorData } },
  sparse: { ...props, data: { decodedContent: { ...investorData, investors: [{ name: 'Alex Sample' }], result_count: 1 } } },
  long: { ...props, data: { decodedContent: { ...investorData, investors: [{ ...investorData.investors[0], name: 'An Investor With An Extremely Long Display Name That Must Wrap Instead Of Overflowing The Card', thesis: 'A long investment thesis sentence that keeps going. '.repeat(30), contact_route: 'https://example.org/a/very/long/contact/route/that/has/no/natural/break/points/at/all/in/it' }] } } },
};
