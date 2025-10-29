import type { DemoChat } from '../../demo_chats/types';

export const termsOfUseChat: DemoChat = {
	chat_id: 'legal-terms',
	slug: 'terms',
	title: 'Terms of Use',
	description: 'Usage terms, rules, and conditions for OpenMates services',
	keywords: ['terms', 'conditions', 'usage', 'rules', 'agreement', 'legal'],
	messages: [
		{
			id: 'terms-1',
			role: 'assistant',
			content: `# Terms of Use 📜

*Last updated: January 1, 2025*  
*Version: 1.0*

Welcome! Let me explain the rules for using OpenMates in plain language.

---

## 1. Agreement to Terms

By using OpenMates, you agree to these Terms and all applicable laws.

---

## 2. What You Can (and Can't) Do

### ✅ You CAN:
- Use OpenMates for personal or commercial purposes
- Access all AI Mates and Apps
- Store your encrypted data
- Use credits to pay for services

### ❌ You CANNOT:
- Violate laws or abuse the system
- Share your account credentials
- Try to hack or overload our servers
- Use the service for illegal activities
- Reverse engineer our software (except where law permits)

---

## 3. Your Content & Data

### Your Rights:
- **You own your content** - We never claim rights to what you create
- **End-to-end encryption** - We cannot read your data
- **Your responsibility** - Keep your encryption keys safe!

### Important Warning:
⚠️ **If you lose your encryption keys, your data is gone forever.**  
We cannot recover it. Back up your keys!

---

## 4. Service Availability

### Uptime:
- We aim for 24/7 availability
- Occasional maintenance windows (we'll notify you)
- No guarantee of 100% uptime

### Changes:
- We may modify features and functionality
- We'll notify you of significant changes
- Continued use after changes = acceptance

---

## 5. Credits & Billing

### How Credits Work:
- **Pay with credits** - Like arcade tokens for AI services
- **Buy in advance** - Purchase credit packages
- **Credits don't expire** (unless you delete your account)
- **No refunds** (except where legally required)

### Pricing:
- Prices may change with 30 days notice
- Existing credit balances keep their value
- Usage costs deducted from your balance

---

## 6. Account Termination

### You Can Leave Anytime:
- Close your account in Settings
- Unused credits are forfeited (except where legally required)
- Your encrypted data will be deleted

### We Can Terminate If:
- You violate these Terms
- You don't pay for services
- With 30 days notice (without cause)

---

## 7. Disclaimers

### "As-Is" Service:
THE SERVICE IS PROVIDED "AS IS" WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED.

### Liability Limits:
WE ARE NOT LIABLE FOR:
- Indirect or consequential damages
- Loss of data (except due to our negligence)
- Service interruptions
- Third-party actions

**Maximum Liability:** Amount you paid in the last 12 months

---

## 8. Your Responsibilities

You agree to indemnify OpenMates against claims from:
- Your violation of these Terms
- Your violation of any law
- Your violation of others' rights

---

## 9. Governing Law

**Jurisdiction:** German law  
**Disputes:** Subject to German courts

---

## 10. Changes to Terms

- We may update these Terms
- Significant changes will be announced
- Continued use after changes = acceptance

---

## 11. Contact

**Questions about these Terms?**  
Email: legal@openmates.org  
Address: See our [Imprint](/imprint) page

---

## Quick Summary (Not Legally Binding)

**In Plain Language:**
- ✅ Be respectful and legal
- ✅ Your data is yours and encrypted
- ✅ We charge credits for usage
- ✅ We can't access your encrypted content
- ✅ Keep your encryption keys safe
- ✅ Standard liability limitations apply

**The full Terms above are the legally binding agreement.**

Questions? Feel free to ask me anything!`,
			timestamp: '2025-01-01T00:00:00Z'
		}
	],
	follow_up_suggestions: [
		"What happens if I lose my encryption keys?",
		"How do credits work?",
		"Can I get a refund on unused credits?",
		"What are the restrictions on using the service?",
		"How can I close my account?"
	],
	metadata: {
		category: 'legal_law',
		icon_names: ['file-text', 'scale', 'shield'],
		featured: false, // Don't show in regular sidebar
		order: 2,
		lastUpdated: '2025-01-01T00:00:00Z'
	}
};
