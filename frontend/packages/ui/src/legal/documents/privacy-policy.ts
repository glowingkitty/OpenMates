import type { DemoChat } from '../../demo_chats/types';

export const privacyPolicyChat: DemoChat = {
	chat_id: 'legal-privacy',
	slug: 'privacy',
	title: 'Privacy Policy',
	description: 'How OpenMates protects your data and privacy - GDPR compliant, end-to-end encrypted, zero-knowledge architecture',
	keywords: ['privacy', 'data protection', 'GDPR', 'encryption', 'security', 'zero-knowledge'],
	messages: [
		{
			id: 'privacy-1',
			role: 'assistant',
			content: `# Privacy Policy 🔒

*Last updated: January 1, 2025*  
*Version: 1.0*

Welcome! Let me explain how we protect your privacy at OpenMates.

## Our Core Commitment

**End-to-End Encryption + Zero-Knowledge Architecture**

This means:
- Your messages are encrypted on **your device**
- We store encrypted data (gibberish to us)
- **We literally cannot read your messages** (not "won't" - we CAN'T!)
- Even government agencies can't force us to decrypt (we don't have the keys!)

---

## 1. Data Controller

**OpenMates**  
[Address]  
Germany  
Email: privacy@openmates.org

---

## 2. What Data We Collect

### ✅ Data We CAN See (Unencrypted):
- **Account Information**: Email address, username, profile picture (optional)
- **Billing Data**: Credit balance, transaction history
- **Usage Metadata**: Number of messages sent, tokens used (not the content!)
- **Technical Data**: IP address (security), browser type, device info

### 🔒 Data We CANNOT See (End-to-End Encrypted):
- **All chat messages** - Your conversations
- **Chat titles** - What you name your chats
- **Drafts** - Your unfinished messages
- **Attachments** - Any files you upload
- **Settings** - Most preferences are encrypted

**Why can't we see it?** Your data is encrypted with keys stored only on your devices. We never have access to these keys.

---

## 3. How We Use Your Data

### Account Data (Unencrypted):
- Create and manage your account
- Process payments
- Send service notifications
- Prevent fraud and abuse

### Encrypted Data:
- **Store it** (encrypted)
- **Sync it** between your devices
- **Cannot read it** (we don't have the keys!)
- **Cannot sell it** (we can't even access it!)

### Technical Data:
- Improve service performance
- Debug technical issues
- Prevent abuse and attacks
- Comply with legal obligations

---

## 4. Legal Basis (GDPR)

We process your data based on:

**Contract Performance (Art. 6(1)(b)):**  
Providing the AI assistant service you signed up for

**Legitimate Interest (Art. 6(1)(f)):**  
Security, fraud prevention, service improvement

**Consent (Art. 6(1)(a)):**  
Where explicitly given (e.g., marketing emails - opt-in only)

**Legal Obligation (Art. 6(1)(c)):**  
Tax records, legal compliance

---

## 5. Data Sharing

### ❌ We DO NOT:
- Sell your data
- Share encrypted content (we can't!)
- Give data to advertisers
- Train AI models on your private chats
- Track you across websites

### ✅ We DO Share With:
**Payment Processors:**  
- Stripe, PayPal (only for billing, minimal data)

**AI Providers (for processing your requests):**  
- OpenAI, Anthropic, Google (encrypted in transit)
- They process requests but don't store your chats
- We send encrypted requests with your keys

**Law Enforcement:**  
- Only with valid legal orders
- Only unencrypted metadata (we can't decrypt content!)

---

## 6. Your Rights (GDPR)

You have the right to:

📥 **Access** - Request a copy of your data  
✏️ **Rectification** - Correct inaccurate data  
🗑️ **Erasure** - Delete your account and data  
⏸️ **Restriction** - Limit how we process your data  
📤 **Portability** - Export your data  
🚫 **Object** - Object to certain processing  
❌ **Withdraw Consent** - Stop marketing emails, etc.  
📢 **Complain** - File complaints with data protection authorities

**How to exercise these rights:**  
Email privacy@openmates.org or use Settings → Privacy

---

## 7. Data Retention

**Encrypted Chat Data:**  
Stored until you delete it (no automatic deletion)

**Account Data:**  
Kept while account is active, deleted 30 days after closure

**Logs & Analytics:**  
Security logs kept for 90 days, then anonymized

**Legal Compliance:**  
Tax records: 7 years (German law requirement)

---

## 8. Security Measures

**Encryption:**
- End-to-end encryption (AES-256)
- Zero-knowledge architecture
- Local key storage (IndexedDB)

**Transmission Security:**
- TLS 1.3 for all connections
- Certificate pinning

**Storage Security:**
- Encrypted databases
- Regular security audits
- Penetration testing

**Access Controls:**
- Strict employee access policies
- 2FA for all team members
- Audit logs for all data access

---

## 9. Cookies & Tracking

### Essential Cookies (Required):
- Session management
- Security (CSRF protection)
- Authentication

### ❌ NO Tracking:
- No advertising cookies
- No third-party analytics
- No cross-site tracking
- No fingerprinting

---

## 10. Children's Privacy

OpenMates is not intended for users under **16 years old** (GDPR requirement).

We do not knowingly collect data from children. If we discover underage usage, we will delete the account immediately.

---

## 11. International Transfers

**Primary Storage:** EU data centers (Germany/Ireland)

**AI API Calls:** May involve transfers to USA (OpenAI, Anthropic, Google)

**Protection:**
- Standard Contractual Clauses (SCCs)
- EU-US Data Privacy Framework
- Your encrypted data is protected regardless of location

---

## 12. Data Breaches

If a breach occurs:
- We notify you within **72 hours** (GDPR requirement)
- Email notification with details
- Steps we're taking to fix it
- Recommendations for protecting yourself

**Your encrypted data is safe:** Even in a breach, we can't decrypt it (we don't have your keys!)

---

## 13. Changes to This Policy

- We may update this policy from time to time
- Significant changes announced via email
- Continued use after changes = acceptance

---

## 14. Contact & Complaints

**Privacy Questions:** privacy@openmates.org  
**Data Protection Officer:** dpo@openmates.org

**File a Complaint:**  
German Federal Commissioner for Data Protection (BfDI)  
Or your local EU data protection authority

---

## 15. Open Source

Our code is open source and auditable:  
[GitHub Repository](https://github.com/openmates)

You can verify our encryption implementation yourself!

---

## Quick Summary

**TL;DR:**
- ✅ End-to-end encryption for all chats
- ✅ Zero-knowledge (we can't read your messages)
- ✅ GDPR compliant
- ✅ No tracking or ads
- ✅ You control your data
- ✅ Open source

**Questions? Just ask!** I'm here to explain anything about privacy.`,
			timestamp: '2025-01-01T00:00:00Z'
		}
	],
	follow_up_suggestions: [
		"Can you really not read my messages?",
		"How does zero-knowledge encryption work?",
		"What if I lose my encryption key?",
		"Do AI providers see my messages?",
		"How do I delete my account?",
		"What data do you share with third parties?"
	],
	metadata: {
		category: 'legal_law', // Leon - the legal expert
		icon_names: ['shield-check', 'lock', 'eye-off'], // Security + encryption + privacy
		featured: false, // Don't show in regular sidebar
		order: 1, // Order in legal documents menu
		lastUpdated: '2025-01-01T00:00:00Z'
	}
};

