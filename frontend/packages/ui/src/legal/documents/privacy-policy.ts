import type { LegalDocument } from '../types';

/**
 * Privacy Policy - GDPR & TTDSG Compliant
 * This document explains how OpenMates handles user data
 */
export const privacyPolicy: LegalDocument = {
	id: 'privacy',
	title: 'Privacy Policy',
	version: 'v1.0',
	effectiveDate: '2025-01-01',
	lastUpdated: '2025-01-01',
	route: '/privacy',
	metadata: {
		description: 'Learn how OpenMates protects your privacy with end-to-end encryption and zero-knowledge architecture',
		keywords: ['privacy', 'GDPR', 'data protection', 'encryption', 'zero-knowledge', 'TTDSG'],
		language: 'en'
	},
	sections: [
		{
			id: 'introduction',
			title: 'Introduction',
			content: `# Privacy Policy

**Last Updated:** January 1, 2025  
**Version:** 1.0

Welcome to OpenMates. We take your privacy seriously. This Privacy Policy explains how we collect, use, protect, and share your personal data when you use our AI-powered assistant service.

**Our Commitment:**
- 🔒 **End-to-end encryption** for all your chats
- 🛡️ **Zero-knowledge architecture** - we can't read your messages
- 🇪🇺 **GDPR compliant** - full EU data protection rights
- 📱 **Your data, your control** - export or delete anytime

This policy complies with:
- **GDPR (EU Regulation 2016/679)**
- **TTDSG (German Telecommunications and Telemedia Data Protection Act)**
- **ePrivacy Directive**`
		},
		{
			id: 'data-controller',
			title: 'Data Controller',
			content: `## 1. Who Controls Your Data

**Data Controller:**  
[Company Name]  
[Address]  
[City, Postal Code, Country]  
Email: privacy@openmates.org  
Phone: [Phone Number]

**Data Protection Officer:**  
Email: dpo@openmates.org

You can contact us anytime regarding your privacy rights or data protection concerns.`
		},
		{
			id: 'data-collection',
			title: 'What Data We Collect',
			content: `## 2. Data We Collect

### 2.1 Data You Provide

**Account Information (Not Encrypted):**
- Email address
- Username
- Profile picture (optional)
- Language preference

**Chat Data (End-to-End Encrypted):**
- All chat messages and conversations
- Chat titles and summaries
- Follow-up suggestions
- Draft messages
- Scroll positions

### 2.2 Automatically Collected Data

**Technical Data:**
- IP address (for security and fraud prevention)
- Browser type and version
- Device information
- Operating system
- Session data
- Usage statistics (anonymized)

**Cookies & Similar Technologies:**
- Authentication cookies (essential)
- Session cookies (essential)
- Analytics cookies (optional, with consent)

See our [Cookie Policy](#cookie-policy) for details.`
		},
		{
			id: 'how-we-use-data',
			title: 'How We Use Your Data',
			content: `## 3. How We Use Your Data

### 3.1 Legal Basis (GDPR Art. 6)

We process your data based on:

**Contract Performance (Art. 6(1)(b)):**
- Providing the AI assistant service
- Processing your requests
- Managing your account

**Legitimate Interests (Art. 6(1)(f)):**
- Improving our services
- Preventing fraud and abuse
- Analyzing usage patterns (anonymized)

**Legal Obligations (Art. 6(1)(c)):**
- Complying with German/EU law
- Tax and accounting requirements
- Responding to legal requests

**Consent (Art. 6(1)(a)):**
- Optional analytics cookies
- Marketing communications (if you opt-in)

### 3.2 Purpose Limitation

We only use your data for:
- ✅ Providing the service you requested
- ✅ Improving service quality
- ✅ Security and fraud prevention
- ✅ Legal compliance
- ❌ **Never for advertising**
- ❌ **Never sold to third parties**`
		},
		{
			id: 'encryption',
			title: 'Encryption & Zero-Knowledge',
			content: `## 4. End-to-End Encryption

### 4.1 How It Works

**Zero-Knowledge Architecture:**
- Your encryption key is generated on your device
- We **never** receive or store your encryption key
- Even we cannot read your encrypted messages
- Government agencies cannot force us to decrypt (we can't!)

**Encryption Standard:**
- **AES-256-GCM** for message content
- **RSA-4096** for key exchange (if multi-device)
- Keys stored locally in IndexedDB (browser)

### 4.2 What's Encrypted

- ✅ All chat messages
- ✅ Chat titles and summaries
- ✅ Follow-up suggestions
- ✅ Draft messages
- ❌ Username and email (needed for login)
- ❌ Usage metadata (chat timestamps, counts)

**Important:** If you forget your password, we **cannot** recover your encrypted chats. They are permanently inaccessible.`
		},
		{
			id: 'data-sharing',
			title: 'Data Sharing & Third Parties',
			content: `## 5. Who We Share Data With

### 5.1 Service Providers (Data Processors)

We use trusted third-party services:

**Hosting & Infrastructure:**
- **Vercel** (USA) - Web hosting (EU data centers available)
- **Supabase** (USA) - Database hosting (EU region)
- **Cloudflare** (USA) - CDN and DDoS protection

**AI Models:**
- **Anthropic** (USA) - Claude API (encrypted requests only)
- **OpenAI** (USA) - GPT models (encrypted requests only)
- **Google** (USA) - Gemini API (encrypted requests only)

All processors are:
- ✅ GDPR compliant
- ✅ EU-US Data Privacy Framework certified (or EU hosted)
- ✅ Bound by data processing agreements (DPAs)

### 5.2 Legal Disclosures

We may disclose data when required by law:
- Court orders or subpoenas
- Law enforcement requests (with legal basis)
- National security demands

**Transparency:** We will notify you unless legally prohibited.

### 5.3 No Data Selling

We **never** sell your data to:
- ❌ Advertisers
- ❌ Data brokers
- ❌ Marketing companies
- ❌ Anyone else`
		},
		{
			id: 'data-retention',
			title: 'Data Retention',
			content: `## 6. How Long We Keep Your Data

**Encrypted Chat Data:**
- Stored until you delete it
- No automatic deletion

**Account Data:**
- Kept while your account is active
- Deleted 30 days after account deletion request

**Logs & Analytics:**
- Kept for 90 days (security logs)
- Anonymized after 90 days

**Legal Compliance:**
- Tax records: 10 years (German law)
- Payment records: As required by law`
		},
		{
			id: 'your-rights',
			title: 'Your GDPR Rights',
			content: `## 7. Your Rights (GDPR Chapter III)

You have the right to:

**Access (Art. 15):** Request a copy of your data  
**Rectification (Art. 16):** Correct inaccurate data  
**Erasure (Art. 17):** Delete your data ("Right to be Forgotten")  
**Restriction (Art. 18):** Limit how we process your data  
**Portability (Art. 20):** Export your data in machine-readable format  
**Object (Art. 21):** Object to data processing  
**Withdraw Consent (Art. 7(3)):** Withdraw consent anytime  

**How to Exercise Your Rights:**
1. Log in to your account → Settings → Privacy
2. Or email: privacy@openmates.org
3. Or write to our postal address

**Response Time:** Within 30 days (may extend to 60 days if complex)

**No Cost:** Exercising your rights is free (unless requests are excessive)`
		},
		{
			id: 'data-breach',
			title: 'Data Breach Notification',
			content: `## 8. Data Breach Protocol

**In Case of a Breach:**
- We will notify you within **72 hours** (GDPR Art. 33)
- Email notification to your registered email
- Details of what data was affected
- Steps we're taking to mitigate harm
- Recommendations for protecting yourself

**Prevention Measures:**
- Regular security audits
- Penetration testing
- Bug bounty program
- Incident response plan`
		},
		{
			id: 'international-transfers',
			title: 'International Data Transfers',
			content: `## 9. International Data Transfers

**Primary Storage:** EU data centers (Germany/Ireland)

**Third-Country Transfers (Non-EU):**
- Based on **Standard Contractual Clauses (SCCs)** (Art. 46 GDPR)
- Or **EU-US Data Privacy Framework** (DPF)
- Or **Adequate level of protection** (Art. 45 GDPR)

**Your Control:**
- You can request EU-only processing (contact us)
- May limit some AI model options`
		},
		{
			id: 'children',
			title: 'Children\'s Privacy',
			content: `## 10. Children's Privacy

**Age Requirement:** You must be **16 years or older** to use OpenMates (GDPR Art. 8).

**Parental Consent:**
- Users under 16 require parental consent
- We do not knowingly collect data from children under 16 without consent
- If we discover underage usage, we will delete the account

**Parents:** Contact us at privacy@openmates.org to review or delete your child's data.`
		},
		{
			id: 'changes',
			title: 'Changes to This Policy',
			content: `## 11. Changes to This Policy

**Updates:**
- We may update this policy from time to time
- Material changes will be notified via email or in-app notification
- You will be asked to re-consent to changes

**Version History:**
- Current version: v1.0 (January 1, 2025)
- Previous versions: [View archived versions](#)`
		},
		{
			id: 'contact',
			title: 'Contact & Complaints',
			content: `## 12. Contact Us

**General Privacy Questions:**  
Email: privacy@openmates.org

**Data Protection Officer:**  
Email: dpo@openmates.org

**Postal Address:**  
[Company Name]  
[Address]  
[City, Postal Code, Country]

**Supervisory Authority (Complaints):**  
If you're unhappy with our response, you can file a complaint with your local data protection authority:

**For Germany:**  
[Your State's Data Protection Authority]  
Website: [Link]

**For EU:**  
Find your authority: https://edpb.europa.eu/about-edpb/board/members_en

---

**Questions?** Ask us anything about privacy in the chat!`
		}
	]
};

