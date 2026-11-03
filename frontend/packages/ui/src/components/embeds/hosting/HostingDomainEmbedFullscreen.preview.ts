import { domainFixtures } from './hostingPreviewFixtures';

const forDomain = (domain: (typeof domainFixtures)[keyof typeof domainFixtures]) => ({
  embedId: domain.embed_id,
  data: { decodedContent: domain, embedData: { status: 'finished' } },
  onClose: () => {},
});

const defaultProps = forDomain(domainFixtures.com);
export default defaultProps;
export const variants = {
  authoredUnknowns: {
    data: { decodedContent: {
      type: "hosting_domain", status: "finished", domain_ascii: "example.test",
      authoring: { schema_version: 1, kind: "hosting.hosting_domain", origin: "draft", sources: [] },
    }, embedData: { status: "finished" }, attrs: { app_id: "hosting" } },
  },

  missingData: forDomain(domainFixtures.unknown),
  unavailable: forDomain(domainFixtures.org),
  unknown: forDomain(domainFixtures.unknown),
  premium: forDomain(domainFixtures.premium),
  minTwoYears: forDomain(domainFixtures.minTwoYears),
  missingPrice: forDomain(domainFixtures.missingPrice),
  longIdn: forDomain(domainFixtures.longIdn),
};
