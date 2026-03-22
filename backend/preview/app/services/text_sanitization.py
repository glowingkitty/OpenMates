"""
Text Sanitization for ASCII Smuggling Protection

This module provides protection against ASCII smuggling attacks, which use
invisible Unicode characters to embed hidden instructions that bypass human
review but are processed by LLMs.

This is the FIRST LAYER of defense before LLM-based prompt injection detection.
It removes invisible characters at the character level, ensuring the LLM sees
clean text without hidden instructions.

ASCII SMUGGLING ATTACK VECTORS PROTECTED:
=========================================

1. Unicode Tags (U+E0000-U+E007F):
   - Invisible characters that encode ASCII text
   - E.g., U+E0041 = hidden 'A', U+E0042 = hidden 'B', etc.
   - Primary vector for "ASCII Smuggler" style attacks

2. Variant Selectors (U+FE00-U+FE0F, U+E0100-U+E01EF):
   - Modify appearance of preceding character
   - Can encode hidden data in sequences

3. Zero-Width Characters:
   - ZWSP (U+200B): Zero-Width Space
   - ZWNJ (U+200C): Zero-Width Non-Joiner
   - ZWJ (U+200D): Zero-Width Joiner
   - Word Joiner (U+2060): Prevents line breaks
   - FEFF (U+FEFF): Byte Order Mark

4. Bidirectional Override Characters:
   - LRM, RLM, LRO, RLO, LRE, RLE, PDF, LRI, RLI, FSI, PDI
   - Can hide/reorder text visually

5. Other Invisible Characters:
   - Soft Hyphen, Invisible Operators, etc.

See: docs/architecture/prompt_injection_protection.md
"""

import unicodedata
import logging
from typing import Tuple, Dict, Any, Optional

logger = logging.getLogger(__name__)


# ==============================================================================
# INVISIBLE CHARACTER DEFINITIONS
# ==============================================================================

# Unicode Tags block (U+E0000-U+E007F)
# These map to ASCII characters and are completely invisible in most UIs
UNICODE_TAGS_RANGE = (0xE0000, 0xE007F)

# Variant Selectors (U+FE00-U+FE0F) - 16 standard variant selectors
VARIANT_SELECTORS_STANDARD = (0xFE00, 0xFE0F)

# Variant Selectors Supplement (U+E0100-U+E01EF) - 240 supplementary variant selectors
VARIANT_SELECTORS_SUPPLEMENT = (0xE0100, 0xE01EF)

# Zero-Width Characters - individual codepoints
ZERO_WIDTH_CHARS = {
    0x200B,  # Zero-Width Space (ZWSP)
    0x200C,  # Zero-Width Non-Joiner (ZWNJ)
    0x200D,  # Zero-Width Joiner (ZWJ)
    0x2060,  # Word Joiner (WJ)
    0xFEFF,  # Byte Order Mark / Zero-Width No-Break Space
}

# Bidirectional Text Control Characters
BIDI_CONTROL_CHARS = {
    0x200E,  # Left-to-Right Mark (LRM)
    0x200F,  # Right-to-Left Mark (RLM)
    0x202A,  # Left-to-Right Embedding (LRE)
    0x202B,  # Right-to-Left Embedding (RLE)
    0x202C,  # Pop Directional Formatting (PDF)
    0x202D,  # Left-to-Right Override (LRO)
    0x202E,  # Right-to-Left Override (RLO)
    0x2066,  # Left-to-Right Isolate (LRI)
    0x2067,  # Right-to-Left Isolate (RLI)
    0x2068,  # First Strong Isolate (FSI)
    0x2069,  # Pop Directional Isolate (PDI)
}

# Other Invisible/Formatting Characters
OTHER_INVISIBLE_CHARS = {
    0x00AD,  # Soft Hyphen (SHY)
    0x034F,  # Combining Grapheme Joiner
    0x061C,  # Arabic Letter Mark
    0x115F,  # Hangul Choseong Filler
    0x1160,  # Hangul Jungseong Filler
    0x17B4,  # Khmer Vowel Inherent Aq
    0x17B5,  # Khmer Vowel Inherent Aa
    0x180E,  # Mongolian Vowel Separator (MVS)
    0x2061,  # Function Application
    0x2062,  # Invisible Times
    0x2063,  # Invisible Separator (ISEP)
    0x2064,  # Invisible Plus
    0x206A,  # Inhibit Symmetric Swapping
    0x206B,  # Activate Symmetric Swapping
    0x206C,  # Inhibit Arabic Form Shaping
    0x206D,  # Activate Arabic Form Shaping
    0x206E,  # National Digit Shapes
    0x206F,  # Nominal Digit Shapes
    0x3164,  # Hangul Filler
    0xFFA0,  # Halfwidth Hangul Filler
}

# ASCII Control Characters (except common whitespace)
# We keep: \t (0x09), \n (0x0A), \r (0x0D), space (0x20)
ASCII_CONTROL_CHARS = set(range(0x00, 0x09)) | {0x0B, 0x0C} | set(range(0x0E, 0x20)) | {0x7F}

# Interlinear Annotation Characters
ANNOTATION_CHARS = {
    0xFFF9,  # Interlinear Annotation Anchor
    0xFFFA,  # Interlinear Annotation Separator
    0xFFFB,  # Interlinear Annotation Terminator
}

# Combine all individual invisible characters
ALL_INVISIBLE_CHARS = (
    ZERO_WIDTH_CHARS |
    BIDI_CONTROL_CHARS |
    OTHER_INVISIBLE_CHARS |
    ASCII_CONTROL_CHARS |
    ANNOTATION_CHARS
)


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _decode_unicode_tags(text: str) -> Optional[str]:
    """
    Attempt to decode hidden ASCII text from Unicode Tags.
    
    Unicode Tags encode ASCII by adding 0xE0000 to the ASCII code point.
    E.g., 'A' (0x41) becomes U+E0041.
    
    Args:
        text: Text to scan for Unicode Tags
    
    Returns:
        The decoded hidden text if found, None otherwise
    """
    decoded = []
    for char in text:
        code = ord(char)
        if UNICODE_TAGS_RANGE[0] <= code <= UNICODE_TAGS_RANGE[1]:
            # Extract the ASCII character encoded in the tag
            ascii_code = code - 0xE0000
            if 0 <= ascii_code < 128:
                decoded.append(chr(ascii_code))
    
    return ''.join(decoded) if decoded else None


# ==============================================================================
# MAIN SANITIZATION FUNCTION
# ==============================================================================

def sanitize_text_for_ascii_smuggling(
    text: str,
    log_prefix: str = "",
    include_stats: bool = False
) -> Tuple[str, Dict[str, Any]]:
    """
    Sanitize text to remove ASCII smuggling attack vectors.
    
    This function removes all invisible Unicode characters that could be used
    to embed hidden instructions in text while preserving legitimate content.
    
    PROCESSING STEPS:
    1. Detect and log any hidden Unicode Tags content (security monitoring)
    2. Remove all Unicode Tags characters (U+E0000-U+E007F)
    3. Remove all Variant Selectors
    4. Remove Zero-Width characters
    5. Remove Bidirectional control characters
    6. Remove other invisible/formatting characters
    7. Remove ASCII control characters (except common whitespace)
    8. Normalize Unicode to NFC form
    
    Args:
        text: The input text to sanitize
        log_prefix: Optional prefix for log messages
        include_stats: Whether to include detailed statistics in result
    
    Returns:
        Tuple of:
        - sanitized_text: The cleaned text
        - stats: Dictionary containing sanitization statistics
    """
    # Handle non-string or empty input
    empty_stats = {
        "removed_count": 0,
        "unicode_tags_count": 0,
        "variant_selectors_count": 0,
        "zero_width_count": 0,
        "bidi_control_count": 0,
        "other_invisible_count": 0,
        "hidden_ascii_detected": False,
        "hidden_ascii_content": None
    }
    
    if not isinstance(text, str):
        return str(text) if text else "", empty_stats
    
    if not text:
        return "", empty_stats
    
    # Initialize counters
    unicode_tags_count = 0
    variant_selectors_count = 0
    zero_width_count = 0
    bidi_control_count = 0
    other_invisible_count = 0
    
    # Step 1: Detect hidden Unicode Tags content (for security monitoring)
    hidden_ascii = _decode_unicode_tags(text)
    if hidden_ascii:
        # Log the detected hidden content for security analysis
        logger.warning(
            f"{log_prefix}[ASCII SMUGGLING DETECTED] Found hidden Unicode Tags content: "
            f"'{hidden_ascii[:500]}{'...' if len(hidden_ascii) > 500 else ''}' "
            f"(length: {len(hidden_ascii)} chars)"
        )
    
    # Step 2-7: Remove all invisible characters
    result = []
    for char in text:
        code = ord(char)
        
        # Check Unicode Tags block
        if UNICODE_TAGS_RANGE[0] <= code <= UNICODE_TAGS_RANGE[1]:
            unicode_tags_count += 1
            continue
        
        # Check Variant Selectors
        if ((VARIANT_SELECTORS_STANDARD[0] <= code <= VARIANT_SELECTORS_STANDARD[1]) or
            (VARIANT_SELECTORS_SUPPLEMENT[0] <= code <= VARIANT_SELECTORS_SUPPLEMENT[1])):
            variant_selectors_count += 1
            continue
        
        # Check Zero-Width characters
        if code in ZERO_WIDTH_CHARS:
            zero_width_count += 1
            continue
        
        # Check BiDi control characters
        if code in BIDI_CONTROL_CHARS:
            bidi_control_count += 1
            continue
        
        # Check other invisible characters (includes ASCII control chars)
        if code in OTHER_INVISIBLE_CHARS or code in ASCII_CONTROL_CHARS or code in ANNOTATION_CHARS:
            other_invisible_count += 1
            continue
        
        # Character is safe, keep it
        result.append(char)
    
    # Step 8: Normalize Unicode to NFC form
    sanitized_text = unicodedata.normalize('NFC', ''.join(result))
    
    # Calculate total removed
    total_removed = (
        unicode_tags_count +
        variant_selectors_count +
        zero_width_count +
        bidi_control_count +
        other_invisible_count
    )
    
    # Log if characters were removed
    if total_removed > 0:
        logger.info(
            f"{log_prefix}[ASCII SMUGGLING SANITIZATION] Removed {total_removed} invisible characters: "
            f"Unicode Tags={unicode_tags_count}, "
            f"Variant Selectors={variant_selectors_count}, "
            f"Zero-Width={zero_width_count}, "
            f"BiDi Controls={bidi_control_count}, "
            f"Other Invisible={other_invisible_count}"
        )
    
    stats = {
        "removed_count": total_removed,
        "unicode_tags_count": unicode_tags_count,
        "variant_selectors_count": variant_selectors_count,
        "zero_width_count": zero_width_count,
        "bidi_control_count": bidi_control_count,
        "other_invisible_count": other_invisible_count,
        "hidden_ascii_detected": hidden_ascii is not None,
        "hidden_ascii_content": hidden_ascii if include_stats else None
    }
    
    return sanitized_text, stats


def sanitize_text_simple(text: str, log_prefix: str = "") -> str:
    """
    Simple wrapper that returns only the sanitized text.
    
    Use this for cases where you don't need the statistics.
    
    Args:
        text: The input text to sanitize
        log_prefix: Optional prefix for log messages
    
    Returns:
        The sanitized text with all invisible characters removed
    """
    sanitized, _ = sanitize_text_for_ascii_smuggling(text, log_prefix, include_stats=False)
    return sanitized
