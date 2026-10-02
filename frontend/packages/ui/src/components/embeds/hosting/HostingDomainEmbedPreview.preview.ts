import { domainFixtures } from './hostingPreviewFixtures';

const defaultProps = { id: domainFixtures.net.embed_id, domain: domainFixtures.net, presentationOnly: true, onFullscreen: () => {} };
export default defaultProps;
export const variants = {
  unavailable: { ...defaultProps, id: domainFixtures.org.embed_id, domain: domainFixtures.org },
  unknown: { ...defaultProps, id: domainFixtures.unknown.embed_id, domain: domainFixtures.unknown },
  premium: { ...defaultProps, id: domainFixtures.premium.embed_id, domain: domainFixtures.premium },
  minTwoYears: { ...defaultProps, id: domainFixtures.minTwoYears.embed_id, domain: domainFixtures.minTwoYears },
  missingPrice: { ...defaultProps, id: domainFixtures.missingPrice.embed_id, domain: domainFixtures.missingPrice },
  longIdn: { ...defaultProps, id: domainFixtures.longIdn.embed_id, domain: domainFixtures.longIdn },
  mobile: { ...defaultProps, isMobile: true },
};
