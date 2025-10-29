import type { DemoChat } from '../../demo_chats/types';

export const imprintChat: DemoChat = {
	chat_id: 'legal-imprint',
	slug: 'imprint',
	title: 'Imprint (Impressum)',
	description: 'Legal information about OpenMates - Company details, contact information, and legal disclosures',
	keywords: ['imprint', 'impressum', 'legal notice', 'company', 'contact', 'legal'],
	messages: [
		{
			id: 'imprint-1',
			role: 'assistant',
			content: `# Imprint (Impressum)

*Information pursuant to § 5 TMG (German Telemedia Act)*

## Provider

**OpenMates**
[Legal Company Name]
[Street Address]
[Postal Code, City]
Germany

## Contact

**Email:** contact@openmates.org  
**Phone:** [Phone Number]  
**Support:** support@openmates.org

## Commercial Register

Register Court: [Court Name]  
Register Number: [Register Number]  
VAT ID: [VAT Number] (according to §27a UStG)

## Responsible for Content

[Name]  
[Address]  

*Pursuant to § 55 Abs. 2 RStV (German Interstate Broadcasting Treaty)*

## Dispute Resolution

The European Commission provides a platform for online dispute resolution (ODR): https://ec.europa.eu/consumers/odr

We are neither willing nor obliged to participate in dispute resolution proceedings before a consumer arbitration board.

## Liability for Content

As a service provider, we are responsible for our own content on these pages in accordance with § 7 Abs.1 TMG. However, according to §§ 8 to 10 TMG, we are not obligated to monitor transmitted or stored third-party information or to investigate circumstances that indicate illegal activity.

Obligations to remove or block the use of information under general law remain unaffected. However, liability in this regard is only possible from the time of knowledge of a specific legal violation. Upon becoming aware of such violations, we will remove this content immediately.

## Liability for Links

Our website contains links to external third-party websites, over whose content we have no control. Therefore, we cannot assume any liability for this external content. The respective provider or operator of the pages is always responsible for the content of the linked pages. The linked pages were checked for possible legal violations at the time of linking. Illegal content was not recognizable at the time of linking.

However, permanent monitoring of the content of linked pages is not reasonable without concrete evidence of a violation of the law. Upon becoming aware of legal violations, we will remove such links immediately.

## Copyright

The content and works created by the site operators on these pages are subject to German copyright law. The reproduction, editing, distribution, and any kind of exploitation outside the limits of copyright law require the written consent of the respective author or creator. Downloads and copies of this site are only permitted for private, non-commercial use.

Insofar as the content on this site was not created by the operator, the copyrights of third parties are respected. In particular, third-party content is marked as such. Should you nevertheless become aware of a copyright infringement, please inform us accordingly. Upon becoming aware of legal violations, we will remove such content immediately.

## Data Protection

Information about data protection can be found in our [Privacy Policy](/privacy).

## Open Source

Parts of OpenMates are open source and available under respective licenses. See our [GitHub repository](https://github.com/openmates) for details.

---

*This Imprint complies with German law requirements (§ 5 TMG, § 55 RStV) and EU regulations.*

## What is an Imprint?

In Germany and some EU countries, websites must provide an "Impressum" (imprint) - legal information about who operates the service. It's like a legal ID card for websites.

## Our Information

**Company:** OpenMates  
**Location:** Germany  
**Contact:** contact@openmates.org

## Why This Matters

**Legal Transparency:**
- Required by German law (§ 5 TMG)
- Ensures you know who you're dealing with
- Provides official contact information
- Shows we're a legitimate, accountable company

**Your Rights:**
- You can reach us for legal matters
- File complaints if needed
- Know the responsible parties
- Access dispute resolution mechanisms

## EU Dispute Resolution

The European Commission offers an online dispute resolution platform for consumer issues:  
[https://ec.europa.eu/consumers/odr](https://ec.europa.eu/consumers/odr)

## Liability & Content

**Our Responsibility:**
- We're responsible for our own content
- We check external links when adding them
- We remove illegal content immediately when notified

**Third-party Content:**
- External links are checked before adding
- We're not responsible for external content after linking
- Report any issues to contact@openmates.org

## Copyright

- Our content is protected by German copyright law
- User content belongs to users (end-to-end encrypted!)
- Open source components have their own licenses
- See our [GitHub](https://github.com/openmates) for source code

## Questions?

Feel free to ask me anything about this legal information!`,
			timestamp: '2025-01-01T00:00:00Z'
		}
	],
	follow_up_suggestions: [
		"Why does German law require an Imprint?",
		"How can I contact your legal team?",
		"What open source licenses do you use?",
		"Where is your company registered?"
	],
	
	metadata: {
		category: 'legal_law',
		icon_names: ['building', 'map-pin', 'mail'],
		featured: false, // Don't show in regular sidebar
		order: 3,
		lastUpdated: '2025-01-01T00:00:00Z'
	}
};

