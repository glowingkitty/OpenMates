import { domainFixtures } from './hostingPreviewFixtures';

const forDomain = (domain: (typeof domainFixtures)[keyof typeof domainFixtures]) => ({
  embedId: domain.embed_id,
  data: { decodedContent: domain, embedData: { status: 'finished' } },
  onClose: () => {},
});

const defaultProps = forDomain(domainFixtures.com);
export default defaultProps;
export const variants = {
  unavailable: forDomain(domainFixtures.org),
  unknown: forDomain(domainFixtures.unknown),
  premium: forDomain(domainFixtures.premium),
  minTwoYears: forDomain(domainFixtures.minTwoYears),
  missingPrice: forDomain(domainFixtures.missingPrice),
  longIdn: forDomain(domainFixtures.longIdn),
};
