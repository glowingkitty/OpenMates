# Sensitive Data Redaction Architecture

> This is the planned architecture.

## Overview
This document outlines the architecture for redacting sensitive data (names, phone numbers, emails, addresses, etc.) before sending requests to LLMs. This protects user privacy and ensures PII (Personally Identifiable Information) is not exposed to external AI services.

## Problem Statement
OpenMates processes user requests containing potentially sensitive information before sending them to LLMs. Currently, the system only performs basic text sanitization (removing non-printable characters). This approach leaves PII vulnerable to:
- Exposure to external LLM providers
- Data retention by LLM vendors
- Potential security breaches in third-party systems

## Proposed Solution Architecture

### 1. **Detection and Classification Layer**

#### 1.1 Pattern-Based Detection (Recommended Primary Layer)
Use `data-anonymizer` library for pattern-based PII detection:
- **Email addresses**: Built-in detector
- **Phone numbers**: Built-in detector (international support)
- **Credit/Debit Cards**: Built-in detector (Luhn validation)
- **Custom regex patterns**: Extensible for SSN, zip codes, IP addresses, URLs
- **Speed**: 5-10ms per message
- **Memory**: <50MB
- **Accuracy**: 95%+

**Why data-anonymizer for Phase 1:**
- ✅ Zero ML model overhead (Hetzner CAX11 friendly)
- ✅ Ultra-fast pattern matching
- ✅ Faker integration for realistic replacement
- ✅ GDPR/Privacy compliance focus
- ✅ Reversible mapping support
- ✅ Production-proven

#### 1.2 ML-Based Detection (Phase 2 - Names Only)
For sophisticated detection of person names, organizations, locations:
- **Option A (Recommended)**: spaCy `en_core_web_sm` (13MB, 20-50ms)
- **Option B (Higher Accuracy)**: Presidio with spaCy (50-100ms, better PII detection)
- **Option C (SOTA but Heavy)**: Transformer-based NER like DistilBERT (200-500ms, 400MB+)

**Use case**: Only when text context suggests letter/email (heuristic-based conditional processing)

#### 1.3 Context-Aware Detection
- Skip detection in code blocks, URLs, file paths
- Maintain domain/context-specific patterns
- Account for false positives in technical contexts (e.g., "Python", "Docker")
- Use confidence thresholding for ML-based detection (0.85+ for names)

### 2. **Redaction Strategy**

#### 2.1 Redaction Modes
Four levels of redaction to balance privacy, realism, and context preservation:

**Mode 1: Placeholder Redaction**
```
Original: "My email is john.doe@company.com and phone is 555-123-4567"
Redacted: "My email is [EMAIL_1] and phone is [PHONE_1]"
Pros: Simple, clear
Cons: Obvious redaction, less natural for LLM processing
```

**Mode 2: Fake Data Redaction (Recommended - via data-anonymizer + Faker)**
```
Original: "My email is john.doe@company.com and phone is 555-123-4567"
Redacted: "My email is michael.johnson@example.org and phone is 202-456-1111"
Pros: Realistic, natural text for LLM, maintains context
Cons: Requires mapping to reverse
Implementation: data-anonymizer with Faker backend
```

**Mode 3: Hash-Based Redaction (Reversible)**
```
Original: "My email is john.doe@company.com"
Redacted: "My email is [EMAIL_HASH_a3f8c]"
Pros: Allows reconstruction, consistent redaction
Cons: Less natural, requires mapping
```

**Mode 4: Semantic Redaction (Context-Preserving)**
```
Original: "Call me at 555-123-4567 tomorrow"
Redacted: "Call me at [PHONE_NUMBER] tomorrow"
Pros: Preserves meaning for LLM
Cons: Less privacy (pattern still detectable)
```

**Recommendation for OpenMates**: Use **Mode 2 (Fake Data)** by default
- Maintains text naturalness for better LLM processing
- Still protects PII (external vendor never sees real data)
- Best balance for the use case

#### 2.2 Mapping & Recovery Strategy
Maintain an in-memory mapping during request processing:
```python
{
  "email_1": "john.doe@company.com",
  "phone_1": "555-123-4567",
  "name_1": "John Doe"
}
```

- Store mapping only in-memory or encrypted temporary storage
- Use context window ID as isolation mechanism
- Clear mapping after response generation
- Optional: Allow client-side mapping storage for optional de-redaction

### 3. **Python Library Comparison & Selection**

#### 3.1 Library Options Comparison

| Aspect | data-anonymizer | Presidio | spaCy | Transformers |
|--------|---|---|---|---|
| **Purpose** | Anonymization/Redaction | PII Detection | General NLP | NER SOTA |
| **Installation** | `pip install data-anonymizer` | `pip install presidio-analyzer` | `pip install spacy + model` | `pip install transformers torch` |
| **Model Size** | 0MB (patterns) | 13MB (spaCy sm) | 13-747MB | 200MB-2GB |
| **Memory Usage** | <50MB | ~200MB | 150-300MB | 400MB-2GB |
| **Speed (per msg)** | 5-10ms | 50-100ms | 20-50ms | 100-500ms |
| **Latency Impact** | Negligible | Low | Low | Moderate-High |
| **Setup Complexity** | Very Easy | Moderate | Moderate | Complex |
| **Email Detection** | ✅ Excellent | ✅ Excellent | ⚠️ Good | ✅ Excellent |
| **Phone Detection** | ✅ Excellent | ✅ Excellent | ⚠️ Good | ✅ Excellent |
| **Credit Card** | ✅ Excellent | ✅ Excellent | ❌ No | ✅ Excellent |
| **Name Detection** | ❌ Pattern-only | ✅ ML-based | ✅ ML-based | ✅ SOTA |
| **Faker Integration** | ✅ Yes | ⚠️ Manual | ❌ No | ❌ No |
| **Reversible Mapping** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| **GDPR Focus** | ✅ Yes | ✅ Yes | ❌ No | ❌ No |
| **Hetzner CAX11** | ✅✅ Perfect | ✅ Good | ✅ Good | ⚠️ Tight |
| **Production Ready** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |

#### 3.2 Recommended Strategy for OpenMates

**Optimal Combination: data-anonymizer + spaCy (Conditional)**

```
Phase 1: data-anonymizer (MVP)
├─ Detects: Email, Phone, Credit Cards, Custom patterns
├─ Speed: 5-10ms per message
├─ Memory: <50MB
├─ Output: Fake data replacements via Faker
└─ Coverage: Handles ~90% of PII cases

Phase 2: Add spaCy NER for names (conditional only)
├─ Detects: PERSON entities (high confidence >0.85)
├─ Triggered: Only when text context suggests letter/email
├─ Speed: +20-50ms when triggered
├─ Memory: +150MB (loaded once)
└─ Coverage: Handles remaining ~10% of cases (names in emails)
```

**Why this combination:**
- ✅ Ultra-lightweight (Hetzner CAX11 compatible)
- ✅ Fast baseline (5-10ms) + optional enhancement
- ✅ Faker generates realistic data (better for LLM processing)
- ✅ Minimal complexity while maximizing coverage
- ✅ Proven libraries (both production-ready)

#### 3.3 Hardware Requirements by Configuration

| Configuration | RAM | CPU | Hetzner Plan | Notes |
|---|---|---|---|---|
| **data-anonymizer only** | 512MB | 1 core | CAX11 | Comfortable, no issues |
| **+ spaCy sm (cached)** | 1GB | 2 cores | CAX21 | Recommended for production |
| **+ Presidio** | 1.5GB | 2 cores | CAX21 | Higher accuracy variant |
| **+ Transformers** | 2GB+ | 4 cores | CCX13+ | Overkill, not recommended |

---

### 4. **Implementation Architecture**

#### 4.1 PII Redactor Module (data-anonymizer based)
**Location**: `backend/apps/ai/utils/pii_redactor.py`

```python
from data_anonymizer import Anonymizer
from faker import Faker
import spacy
from typing import List, Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

class PIIRedactor:
    def __init__(self, mode: str = "faker", use_name_detection: bool = False):
        """
        Args:
            mode: "faker" (default, realistic replacement),
                  "placeholder" ([EMAIL], [PHONE]),
                  "hash" (reversible via mapping)
            use_name_detection: Enable spaCy NER for names (Phase 2)
        """
        self.mode = mode
        self.pii_mapping = {}  # Task-scoped mapping
        self.anonymizer = Anonymizer()
        self.faker = Faker()
        self.nlp = None  # Lazy-loaded spaCy model

        if use_name_detection:
            self._load_spacy_model()

    def _load_spacy_model(self):
        """Lazy-load spaCy model (singleton pattern)"""
        if self.nlp is None:
            try:
                self.nlp = spacy.load("en_core_web_sm")
                logger.info("Loaded spaCy en_core_web_sm for name detection")
            except OSError:
                logger.warning("spaCy model not found. Install with: python -m spacy download en_core_web_sm")
                self.nlp = None

    async def redact_message_history(
        self,
        message_history: List[Dict],
        context_id: str
    ) -> Tuple[List[Dict], Dict[str, str]]:
        """
        Redacts all messages in history using data-anonymizer.

        Returns:
            (redacted_messages, pii_mapping)
        """
        self.pii_mapping = {}
        redacted_messages = []

        for msg in message_history:
            msg_dict = msg.copy()
            if isinstance(msg.get("content"), str):
                redacted_content, mapping = await self.redact_text(
                    msg["content"],
                    context_id
                )
                msg_dict["content"] = redacted_content
                self.pii_mapping.update(mapping)

            redacted_messages.append(msg_dict)

        logger.info(f"Redacted {len(message_history)} messages. Found {len(self.pii_mapping)} PII items.")
        return redacted_messages, self.pii_mapping

    async def redact_text(self, text: str, context_id: str) -> Tuple[str, Dict[str, str]]:
        """
        Redact single text string using data-anonymizer.

        Returns:
            (redacted_text, mapping_dict)
        """
        if not text:
            return text, {}

        mapping = {}
        redacted = text

        # Phase 1: Use data-anonymizer for emails, phones, credit cards
        if self.mode == "faker":
            # Use built-in Faker replacement in data-anonymizer
            result = self.anonymizer.anonymize(
                text,
                providers=['email', 'phone_number', 'credit_card']
            )
            redacted = result['text']
            # data-anonymizer provides mapping in result
            mapping.update(result.get('mapping', {}))

        elif self.mode == "placeholder":
            # Custom placeholder logic
            result = self.anonymizer.anonymize(
                text,
                providers=['email', 'phone_number', 'credit_card'],
                replace_with='placeholder'  # or implement custom
            )
            redacted = result['text']
            mapping.update(result.get('mapping', {}))

        # Phase 2: Optional name detection via spaCy
        if self.nlp is not None and self._should_detect_names(text):
            doc = self.nlp(redacted)
            for ent in doc.ents:
                if ent.label_ == "PERSON" and ent.ent_iob_ == "B":  # First mention
                    fake_name = self.faker.name()
                    redacted = redacted.replace(ent.text, fake_name, 1)
                    mapping[ent.text] = fake_name
                    logger.debug(f"Redacted name: {ent.text} → {fake_name}")

        return redacted, mapping

    def _should_detect_names(self, text: str) -> bool:
        """
        Heuristic to determine if we should apply name detection.
        Reduces false positives on technical text.
        """
        # Skip if text contains code blocks, URLs, file paths
        if any(indicator in text for indicator in ['```', 'http://', 'https://', '/', '.py', '.js']):
            return False

        # Detect if text looks like a letter/email (salutation patterns)
        letter_indicators = ['Dear', 'Hello', 'Hi', 'Greetings', 'To whom']
        return any(text.startswith(ind) for ind in letter_indicators)

    def recover_from_redacted(
        self,
        redacted_text: str,
        mapping: Dict[str, str]
    ) -> str:
        """
        Reverse redaction using mapping (optional, for de-redaction).
        """
        recovered = redacted_text
        # Simple reversal - in production might want bidirectional mapping
        for original, replacement in mapping.items():
            recovered = recovered.replace(replacement, original)
        return recovered
```

#### 4.2 Integration with Preprocessor

```python
# In preprocessor.py - handle_preprocessing()

from backend.apps.ai.utils.pii_redactor import PIIRedactor

async def handle_preprocessing(
    request_data: AskSkillRequest,
    # ... other params
) -> PreprocessingResult:
    log_prefix = f"Preprocessor (ChatID: {request_data.chat_id}):"

    # Initialize redactor (Phase 1: data-anonymizer only)
    pii_redactor = PIIRedactor(
        mode="faker",  # Realistic replacement
        use_name_detection=False  # Enable in Phase 2
    )

    # Redact message history
    sanitized_message_history, pii_mapping = await pii_redactor.redact_message_history(
        message_history=request_data.message_history,
        context_id=request_data.chat_id
    )

    logger.info(f"{log_prefix} Redacted {len(pii_mapping)} PII items before LLM call")

    # Use redacted_message_history for LLM call instead of raw messages
    llm_call_result = await call_preprocessing_llm(
        task_id=f"{request_data.chat_id}_{request_data.message_id}",
        model_id=preprocessing_model,
        message_history=sanitized_message_history,  # ← Use redacted version
        # ... rest of params
    )

    # Store mapping in context for potential recovery later
    # (Don't expose to LLM, clear after response)
    request_data._pii_mapping = pii_mapping

    # ... rest of preprocessing logic
```

#### 4.3 Installation & Requirements

**Phase 1 (MVP) - requirements.txt**
```
data-anonymizer>=0.2.0
faker>=12.0.0
```

**Phase 2 (Enhanced) - additional requirements**
```
spacy>=3.5.0
# Then download model:
# python -m spacy download en_core_web_sm (13MB)
```

**Installation steps:**
```bash
# Phase 1
pip install data-anonymizer faker

# Phase 2 (when ready)
pip install spacy
python -m spacy download en_core_web_sm
```

#### 4.4 Integration Points

**Point 1: Preprocessing Stage** (`preprocessor.py`)
```python
# In handle_preprocessing()
pii_redactor = PIIRedactor(mode="placeholder")
redacted_history, pii_mapping = await pii_redactor.redact_message_history(
    message_history=request_data.message_history,
    context_id=request_data.chat_id
)
# Use redacted_history for LLM call instead of sanitized_message_history
```

**Point 2: LLM Call** (`llm_utils.py`)
```python
# In call_preprocessing_llm() and call_main_llm_stream()
# Use pre-redacted message history
transformed_messages_for_llm = _transform_message_history_for_llm(redacted_message_history)
```

**Point 3: Response Post-Processing** (`postprocessor.py`)
```python
# After LLM completes, optionally de-redact for user visibility
recovered_response = pii_redactor.recover_from_redacted(
    llm_response,
    pii_mapping
)
# Return recovered version to user (optional based on config)
```

#### 4.5 Configuration
**File**: `backend/apps/ai/config/redaction_config.yml`

```yaml
redaction:
  enabled: true
  method: "data-anonymizer"  # data-anonymizer (Phase 1), presidio (Phase 2), spacy (fallback)
  mode: "faker"  # faker (realistic), placeholder ([EMAIL]), hash (reversible)

  # Phase 1: data-anonymizer configuration
  data_anonymizer:
    providers:
      - email
      - phone_number
      - credit_card

    custom_patterns:
      ssn:
        pattern: '\d{3}-\d{2}-\d{4}'
        enabled: true
      zip_code:
        pattern: '\b\d{5}(-\d{4})?\b'
        enabled: false
      ip_address:
        pattern: '\b(?:\d{1,3}\.){3}\d{1,3}\b'
        enabled: false

  # Phase 2: Optional NER for names
  name_detection:
    enabled: false  # Enable in Phase 2
    method: "spacy"  # spacy, presidio
    model: "en_core_web_sm"  # spaCy model size
    confidence_threshold: 0.85

    context_filters:
      skip_code_blocks: true
      skip_urls: true
      skip_file_paths: true
      detect_letter_patterns: true  # Only when text looks like letter

    false_positive_whitelist:
      - Python
      - JavaScript
      - Docker
      - Kubernetes
      - Microsoft
      - Google
      - Amazon
      - Apple
      - January
      - February
      - Monday
      - Tuesday

  # Storage & lifecycle
  storage:
    mapping_ttl_seconds: 3600  # Auto-clear after 1 hour
    encrypt_mapping: false  # false for Phase 1 (memory-only)

  # Monitoring & logging
  logging:
    log_detection_events: true
    log_redaction_details: false  # Never log actual PII
    log_performance_metrics: true
```

### 4. **Data Flow Diagram**

```
User Input
    ↓
[Preprocessing - Redaction Stage]
    ├─ Detect PII (patterns + optional ML)
    ├─ Create PII Mapping (context-scoped)
    ├─ Redact Message History
    └─ Store mapping in context
    ↓
[Sanitization] (existing code)
    ↓
[LLM Call] with redacted messages
    ├─ Preprocessing LLM (safety checks)
    └─ Main LLM (response generation)
    ↓
[Response Post-Processing]
    ├─ Optional: De-redact response using mapping
    └─ Clear PII mapping
    ↓
User receives response (original PII restored or kept redacted)
```

### 5. **Security Considerations**

#### 5.1 Threat Model
| Threat | Mitigation |
|--------|-----------|
| LLM vendor data retention | Redaction prevents exposure |
| Network interception | HTTPS + encryption at rest |
| Memory dumps | Encrypt mapping in memory |
| Timing attacks | Use consistent redaction format |
| Reconstruction from context | Use semantic redaction mode |

#### 5.2 Privacy Best Practices
- **Minimize Exposure**: Only send redacted data to LLM
- **Limited Retention**: Clear mappings after request completes
- **Audit Trail**: Log PII detection (not the actual PII) for compliance
- **User Control**: Allow users to opt-in to full/redacted processing
- **Transparent**: Inform users that PII is redacted before sending

### 6. **Implementation Phases**

#### Phase 1: MVP (Weeks 1-2) - data-anonymizer Focus
**Goal**: Protect ~90% of cases with minimal overhead

- ✅ Install `data-anonymizer` + `faker`
- ✅ Implement PIIRedactor class with "faker" mode
- ✅ Pattern-based detection: email, phone, credit cards
- ✅ Realistic fake data replacement (via Faker)
- ✅ Integration in `handle_preprocessing()`
- ✅ PII mapping storage (in-memory, task-scoped)
- ✅ Configuration YAML setup
- ✅ Logging (detection events, no actual PII)
- ✅ Add custom patterns: SSN (optional)

**Requirements**:
```
data-anonymizer>=0.2.0
faker>=12.0.0
```

**Performance**: 5-10ms per message, <50MB memory
**Hardware**: Hetzner CAX11 ✅ Comfortable

#### Phase 2: Enhanced (Weeks 3-4) - Name Detection
**Goal**: Improve coverage to ~98%+ with optional spaCy NER

- Add spaCy `en_core_web_sm` for name detection
- Implement conditional name detection (heuristic-based)
- Add confidence thresholding (0.85+)
- Implement false-positive whitelist
- Add context filtering (skip code/URLs/paths)
- Update configuration for Phase 2 options
- Integration testing with letter/email samples

**Requirements**: Add `spacy>=3.5.0` (13MB model)

**Performance**: +20-50ms when name detection triggered
**Hardware**: Hetzner CAX21+ ✅ Recommended

#### Phase 3: Advanced (Months 2+) - Optional Enhancements
- Upgrade to Presidio for higher accuracy (if needed)
- Encrypted mapping storage
- De-redaction in post-processor (optional user-facing)
- User preferences for redaction level
- Privacy policy updates & compliance docs
- Monitoring dashboard for PII detection stats
- Custom domain-specific patterns

### 7. **Testing Strategy**

#### 7.1 Unit Tests
```python
# test_pii_redactor.py
import pytest
from backend.apps.ai.utils.pii_redactor import PIIRedactor

@pytest.mark.asyncio
async def test_email_redaction():
    redactor = PIIRedactor(mode="faker")
    text = "Contact me at john@example.com"
    redacted, mapping = await redactor.redact_text(text, "test_ctx")

    assert "john@example.com" in mapping.values()
    assert "john@example.com" not in redacted
    assert "@" in redacted  # Still contains email-like structure

@pytest.mark.asyncio
async def test_phone_redaction():
    redactor = PIIRedactor(mode="faker")
    text = "My phone is 555-123-4567"
    redacted, mapping = await redactor.redact_text(text, "test_ctx")

    assert any("555" in str(v) for v in mapping.keys())
    assert "555-123-4567" not in redacted
    assert len(mapping) > 0

@pytest.mark.asyncio
async def test_message_history_redaction():
    redactor = PIIRedactor(mode="faker")
    history = [
        {"role": "user", "content": "My email is test@example.com"},
        {"role": "assistant", "content": "I'll help you"}
    ]
    redacted, mapping = await redactor.redact_message_history(history, "test_ctx")

    assert redacted[0]["content"] != history[0]["content"]
    assert len(mapping) > 0

@pytest.mark.asyncio
async def test_recovery():
    redactor = PIIRedactor(mode="faker")
    original = "Contact john@example.com"
    redacted, mapping = await redactor.redact_text(original, "test_ctx")

    recovered = redactor.recover_from_redacted(redacted, mapping)
    assert original in recovered or "john@example.com" in recovered
```

#### 7.2 Integration Tests
- Test with real message histories
- Verify LLM receives redacted data
- Test edge cases (repeated PII, embedded PII, special characters)

#### 7.3 Privacy Tests
- False positive rates
- Redaction consistency
- Mapping isolation between requests

### 8. **Performance Considerations**

- **Detection**: ~10-50ms per message (regex only)
- **With ML**: ~100-500ms (Phase 2)
- **Memory**: O(n) where n = number of detected PII items
- **Caching**: Cache compiled regex patterns

### 9. **Configuration Examples**

**Example 1: Maximum Privacy (Strict Mode)**
```yaml
redaction:
  mode: "semantic"
  detection:
    name: {enabled: true, confidence: 0.7}
    email: {enabled: true}
    phone: {enabled: true}
    address: {enabled: true}
    ssn: {enabled: true}
  storage:
    mapping_ttl_seconds: 60
    encrypt_mapping: true
```

**Example 2: Development/Testing (Permissive Mode)**
```yaml
redaction:
  enabled: false  # Skip redaction in dev
```

### 10. **Monitoring & Metrics**

Track:
- PII detection rate per message type
- Redaction mode distribution
- False positive/negative rates
- Processing time impact
- Error rates in recovery

## 11. **Executive Summary: Recommended Implementation**

### For OpenMates on Hetzner:

**Tech Stack:**
- **Phase 1**: `data-anonymizer` + `faker` (5-10ms, <50MB memory)
- **Phase 2**: Add `spacy` small model for names (optional, +20-50ms)

**Redaction Mode:** Fake data (realistic replacement via Faker)

**Result Format:**
```
Before:  "My email is john.doe@company.com and call 555-1234"
After:   "My email is michael.johnson@example.org and call 202-456-1111"
```

**Key Benefits:**
- ✅ PII never exposed to LLM vendors
- ✅ Text naturalness preserved (better LLM processing)
- ✅ Ultra-lightweight (Hetzner CAX11 friendly)
- ✅ Simple to implement (production-ready libraries)
- ✅ Reversible (mapping stored for potential recovery)
- ✅ GDPR/Privacy compliance

**Timeline:**
- Phase 1: 1-2 weeks (emails, phones, cards)
- Phase 2: +1-2 weeks (names, refinements)
- Phase 3: Ongoing (monitoring, enhancements)

---

## Presidio-Based Pseudonymization (Alternative Approach)

**Status**: ⚠️ **EXPERIMENTAL** - Tested and working, but requires more experimentation to determine reliability boundaries.

**Overview**: Microsoft Presidio provides a comprehensive PII detection and anonymization framework that can be used for pseudonymization (replacing PII with placeholders that can be reversed). This approach uses Presidio's `AnalyzerEngine` to detect PII and custom operators to replace detected entities with unique identifiers (e.g., `<PERSON_0>`, `<EMAIL_1>`, `<LOCATION_2>`).

**Test Results**: Initial testing shows processing times of ~150ms for longer texts (~1,200 characters) with multiple PII entities. See [`presidio_pseudonymization.ipynb`](./presidio_pseudonymization.ipynb) for implementation examples and performance benchmarks.

### Architecture

#### Detection & Pseudonymization Flow

1. **Detection Phase**: Use Presidio's `AnalyzerEngine` to identify PII entities in user messages
   - Detects: PERSON, EMAIL, PHONE_NUMBER, LOCATION, ORGANIZATION, CREDIT_CARD, SSN, etc.
   - Uses spaCy models (e.g., `en_core_web_lg`) for entity recognition
   - Returns entity types, positions, and confidence scores

2. **Pseudonymization Phase**: Use custom `AnonymizerEngine` operator to replace PII with placeholders
   - Creates unique identifiers per entity type: `<PERSON_0>`, `<EMAIL_1>`, `<LOCATION_2>`, etc.
   - Maintains entity mapping dictionary: `{entity_type: {original_value: placeholder}}`
   - Stores mapping in-memory during request processing

3. **LLM Processing**: Send pseudonymized text to LLM (no real PII exposed)

4. **De-pseudonymization Phase**: Use `DeanonymizeEngine` to restore original values in LLM response
   - Replaces placeholders back with original PII values
   - Uses same entity mapping from pseudonymization phase
   - Returns text with original PII restored

#### Implementation Example

```python
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine, DeanonymizeEngine, OperatorConfig
from presidio_anonymizer.operators import Operator, OperatorType

# Custom operator for pseudonymization
class InstanceCounterAnonymizer(Operator):
    """Replaces PII with unique identifiers like <PERSON_0>, <EMAIL_1>"""
    REPLACING_FORMAT = "<{entity_type}_{index}>"
    
    def operate(self, text: str, params: Dict = None) -> str:
        entity_type = params["entity_type"]
        entity_mapping = params["entity_mapping"]
        
        # Get or create mapping for this entity type
        entity_mapping_for_type = entity_mapping.get(entity_type, {})
        
        # If already mapped, return existing placeholder
        if text in entity_mapping_for_type:
            return entity_mapping_for_type[text]
        
        # Create new placeholder
        index = len(entity_mapping_for_type)
        placeholder = self.REPLACING_FORMAT.format(
            entity_type=entity_type, index=index
        )
        
        # Store mapping
        entity_mapping[entity_type][text] = placeholder
        return placeholder

# Usage
analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()
anonymizer.add_anonymizer(InstanceCounterAnonymizer)

# Detect PII
analyzer_results = analyzer.analyze(text=user_message, language="en")

# Pseudonymize
entity_mapping = {}
anonymized_result = anonymizer.anonymize(
    user_message,
    analyzer_results,
    {
        "DEFAULT": OperatorConfig(
            "entity_counter", {"entity_mapping": entity_mapping}
        )
    },
)

# Send pseudonymized text to LLM
llm_response = call_llm(anonymized_result.text)

# De-pseudonymize LLM response
deanonymizer = DeanonymizeEngine()
deanonymizer.add_deanonymizer(InstanceCounterDeanonymizer)

deanonymized_response = deanonymizer.deanonymize(
    llm_response,
    anonymized_result.items,
    {"DEFAULT": OperatorConfig("entity_counter_deanonymizer",
                               params={"entity_mapping": entity_mapping})}
)
```

### When Presidio Works Reliably

✅ **Reliable Use Cases**:
- **Structured PII**: Email addresses, phone numbers, credit cards, SSNs (high accuracy)
- **Clear context**: Names in formal documents, letters, emails
- **Well-formed text**: Proper capitalization, punctuation, sentence structure
- **English language**: Best support for English (other languages may require additional models)
- **Single entity mentions**: Each PII entity appears once or in consistent contexts
- **Standard formats**: Phone numbers, addresses, dates in common formats

✅ **Performance Characteristics**:
- **Fast processing**: ~50-150ms for typical messages (1,000-2,000 characters)
- **Memory efficient**: ~200-300MB with spaCy `en_core_web_lg` model
- **Scalable**: Can process multiple messages in sequence
- **Reversible**: Full de-pseudonymization support via entity mapping

### When Presidio May Not Work Reliably

⚠️ **Challenging Scenarios** (Requires More Experimentation):

1. **False Positives**:
   - Technical terms mistaken for names: "Python", "Docker", "JavaScript"
   - Common words: "Monday", "January", "Apple" (company vs. fruit)
   - **Mitigation**: Implement whitelist of known false positives, context-aware filtering

2. **False Negatives**:
   - Uncommon name formats or misspellings
   - Non-standard phone/email formats
   - PII in code blocks or special formatting
   - **Mitigation**: Combine with pattern-based detection, lower confidence thresholds

3. **Context-Dependent Detection**:
   - Names in code comments or technical documentation
   - PII in URLs or file paths
   - Abbreviations or nicknames
   - **Mitigation**: Skip detection in code blocks, implement context filters

4. **Multi-Language Support**:
   - Non-English names and locations
   - Different date/phone formats
   - **Mitigation**: Load appropriate spaCy models per language, configure language-specific patterns

5. **Ambiguous Entities**:
   - "Paris" (city vs. person name)
   - "Jordan" (country vs. person name)
   - **Mitigation**: Use confidence thresholds, context analysis, entity disambiguation

6. **Complex Text Structures**:
   - Nested quotes, code blocks, markdown
   - Tables, lists with PII
   - **Mitigation**: Pre-process text to extract and handle structured content separately

7. **Thread Safety**:
   - Entity mapping must be isolated per request/context
   - Concurrent processing requires careful mapping management
   - **Mitigation**: Use request-scoped mappings, avoid shared state

### Reliability Considerations & Best Practices

#### 1. **Confidence Thresholding**
```python
# Only accept high-confidence detections
analyzer_results = analyzer.analyze(text=text, language="en")
filtered_results = [
    r for r in analyzer_results 
    if r.score >= 0.85  # Adjust threshold based on testing
]
```

#### 2. **Context-Aware Filtering**
```python
# Skip detection in code blocks, URLs, file paths
def should_detect_pii(text: str) -> bool:
    if '```' in text or 'http://' in text or 'https://' in text:
        return False  # Skip technical content
    return True
```

#### 3. **Whitelist Management**
```python
# Known false positives to exclude
FALSE_POSITIVE_WHITELIST = {
    'PERSON': ['Python', 'JavaScript', 'Docker', 'Kubernetes'],
    'LOCATION': ['Monday', 'Tuesday', 'January', 'February'],
    'ORGANIZATION': ['Apple', 'Microsoft', 'Google']  # Context-dependent
}
```

#### 4. **Hybrid Approach**
Combine Presidio with pattern-based detection for better coverage:
- Use Presidio for names, organizations, locations (ML-based)
- Use regex patterns for emails, phones, credit cards (faster, more reliable)
- Merge results and deduplicate

#### 5. **Testing & Validation**
- Test with diverse text samples (emails, letters, technical docs, code)
- Measure false positive/negative rates
- Validate de-pseudonymization accuracy
- Performance benchmarking under load
- Edge case testing (special characters, unicode, formatting)

### Integration Points

**Pre-Processing Stage** (`preprocessor.py`):
```python
# Pseudonymize user messages before sending to LLM
pseudonymized_history, entity_mapping = pseudonymize_message_history(
    message_history=request_data.message_history,
    context_id=request_data.chat_id
)

# Store mapping for later de-pseudonymization
request_data._pii_mapping = entity_mapping

# Use pseudonymized history for LLM calls
llm_result = await call_preprocessing_llm(
    message_history=pseudonymized_history,
    # ... other params
)
```

**Post-Processing Stage** (`postprocessor.py` or response handler):
```python
# De-pseudonymize LLM response before sending to client
depseudonymized_response = depseudonymize_text(
    llm_response,
    entity_mapping=request_data._pii_mapping
)

# Clear mapping after use
del request_data._pii_mapping
```

### Configuration

```yaml
# backend/apps/ai/config/presidio_config.yml
presidio:
  enabled: true
  model: "en_core_web_lg"  # or "en_core_web_sm" for faster processing
  confidence_threshold: 0.85
  
  # Entity types to detect
  entities:
    - PERSON
    - EMAIL_ADDRESS
    - PHONE_NUMBER
    - LOCATION
    - ORGANIZATION
    - CREDIT_CARD
    - SSN
  
  # Context filters
  context_filters:
    skip_code_blocks: true
    skip_urls: true
    skip_file_paths: true
  
  # False positive whitelist
  whitelist:
    PERSON: ["Python", "JavaScript", "Docker"]
    LOCATION: ["Monday", "January"]
  
  # Performance
  cache_model: true  # Keep model in memory
  max_text_length: 10000  # Skip processing for very long texts
```

### Performance Benchmarks

Based on testing with [`presidio_pseudonymization.ipynb`](./presidio_pseudonymization.ipynb):

| Text Length | Entities Found | Analysis Time | Anonymization Time | Total Time |
|-------------|----------------|---------------|-------------------|------------|
| ~100 chars  | 7 entities     | ~50ms         | ~5ms              | ~55ms      |
| ~1,200 chars| 20+ entities   | ~100ms        | ~30ms             | ~150ms     |

**Performance Notes**:
- Analysis phase is typically the bottleneck (spaCy model inference)
- Anonymization/de-anonymization are very fast (simple string replacement)
- Model loading is one-time cost (can be cached)
- Memory usage: ~400MB with `en_core_web_lg` model

### Comparison: Presidio vs. data-anonymizer

| Aspect | Presidio | data-anonymizer |
|--------|----------|-----------------|
| **Detection Method** | ML-based (spaCy) + patterns | Pattern-based only |
| **Name Detection** | ✅ Excellent (ML) | ❌ Pattern-only |
| **Email/Phone** | ✅ Excellent | ✅ Excellent |
| **Speed** | 50-150ms | 5-10ms |
| **Memory** | ~400MB (with model) | <50MB |
| **Accuracy** | Higher (context-aware) | Good (pattern-based) |
| **False Positives** | More (ML can over-detect) | Fewer (strict patterns) |
| **Reversibility** | ✅ Yes (pseudonymization) | ✅ Yes (mapping) |
| **Best For** | Complex text, names, context | Simple patterns, speed |

### Recommendations

**Use Presidio when**:
- You need to detect person names reliably
- Text contains complex, context-dependent PII
- Accuracy is more important than speed
- You have sufficient memory resources (~400MB+)

**Use data-anonymizer when**:
- Speed is critical (<10ms requirement)
- Memory is constrained (<100MB)
- PII is mostly structured (emails, phones, cards)
- Pattern-based detection is sufficient

**Hybrid Approach** (Recommended):
- Use data-anonymizer for structured PII (emails, phones, cards) - fast and reliable
- Use Presidio conditionally for names in specific contexts (letters, emails) - higher accuracy
- Combine results and deduplicate

### Next Steps for Implementation

1. **More Experimentation Needed**:
   - Test with diverse real-world message samples
   - Measure false positive/negative rates
   - Validate edge cases (code blocks, special characters, unicode)
   - Performance testing under production load

2. **Reliability Improvements**:
   - Implement context-aware filtering
   - Build comprehensive whitelist of false positives
   - Add confidence threshold tuning
   - Implement hybrid detection (Presidio + patterns)

3. **Integration Planning**:
   - Determine integration point (pre-processing vs. main processing)
   - Design entity mapping storage (in-memory vs. encrypted cache)
   - Plan for thread-safety in concurrent requests
   - Error handling and fallback strategies

4. **User Experience**:
   - Decide whether to show pseudonymized text to users (transparency)
   - Handle cases where de-pseudonymization fails
   - Provide user controls (opt-in/opt-out)

## References
- OWASP: Sensitive Data Exposure
- data-anonymizer: https://pypi.org/project/data-anonymizer/
- Faker: https://github.com/joke2k/faker
- spaCy NER: https://spacy.io/usage/linguistic-features#named-entities
- Microsoft Presidio: https://github.com/microsoft/presidio
- Presidio Documentation: https://microsoft.github.io/presidio/
- Presidio Pseudonymization Example: [`presidio_pseudonymization.ipynb`](./presidio_pseudonymization.ipynb)
- GDPR Data Protection Best Practices
- ISO 27001: Information Security Management
