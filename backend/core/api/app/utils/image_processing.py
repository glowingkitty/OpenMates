# backend/core/api/app/utils/image_processing.py
#
# Image processing utilities for format conversion and thumbnail generation.
# Uses Pillow for high-performance image manipulation.
# Includes industry-standard AI content labeling via IPTC 2025.1 and C2PA-compatible metadata.

import logging
import io
import xml.etree.ElementTree as ET
from typing import Tuple, Dict, Any, Optional
from PIL import Image

logger = logging.getLogger(__name__)

def process_image_for_storage(
    image_bytes: bytes,
    thumbnail_size: Tuple[int, int] = (600, 400),
    webp_quality: int = 80,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, bytes]:
    """
    Process a raw image (PNG/JPEG) into multiple formats for storage:
    1. Original (preserved as-is)
    2. Full-size WEBP (for editing/fullscreen) with AI metadata
    3. Preview WEBP (scaled down for embeds) with AI metadata
    
    Args:
        image_bytes: The raw image bytes from the provider
        thumbnail_size: Max (width, height) for the preview
        webp_quality: Quality setting for WEBP conversion
        metadata: Optional dictionary of AI metadata for labeling
        
    Returns:
        Dict containing:
        - 'original': bytes
        - 'full_webp': bytes
        - 'preview_webp': bytes
    """
    results = {'original': image_bytes}
    
    try:
        # Load image from bytes
        img = Image.open(io.BytesIO(image_bytes))
        
        # Prepare XMP metadata if provided
        xmp_data = None
        if metadata:
            xmp_data = _generate_ai_xmp(metadata)
        
        # 1. Generate Full-size WEBP
        full_webp_io = io.BytesIO()
        # Use higher quality (90+) for full WEBP to preserve pixel-level signals like SynthID
        img.save(full_webp_io, format="WEBP", quality=90, xmp=xmp_data)
        results['full_webp'] = full_webp_io.getvalue()
        
        # 2. Generate Preview WEBP
        # Logic: 
        # - Horizontal/Square: 600x400 (crop to fit)
        # - Vertical: 400px height, keep aspect ratio
        
        width, height = img.size
        is_vertical = height > width
        
        if is_vertical:
            # Vertical: fixed height 400, proportional width
            new_height = 400
            new_width = int(width * (new_height / height))
            preview_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        else:
            # Horizontal/Square: 600x400
            target_ratio = 600 / 400
            current_ratio = width / height
            
            if current_ratio > target_ratio:
                # Wider than target: crop sides
                new_width = int(height * target_ratio)
                left = (width - new_width) / 2
                img_cropped = img.crop((left, 0, left + new_width, height))
            else:
                # Taller than target: crop top/bottom
                new_height = int(width / target_ratio)
                top = (height - new_height) / 2
                img_cropped = img.crop((0, top, width, top + new_height))
                
            preview_img = img_cropped.resize((600, 400), Image.Resampling.LANCZOS)
            
        preview_webp_io = io.BytesIO()
        # Preview also gets metadata but can use lower quality
        preview_img.save(preview_webp_io, format="WEBP", quality=webp_quality, xmp=xmp_data)
        results['preview_webp'] = preview_webp_io.getvalue()
        
        logger.info(f"Image processed successfully: original={len(image_bytes)}b, full_webp={len(results['full_webp'])}b, preview_webp={len(results['preview_webp'])}b")
        if metadata:
            logger.info(f"AI Metadata injected for model: {metadata.get('model')}")
        
    except Exception as e:
        logger.error(f"Failed to process image: {e}", exc_info=True)
        # If processing fails, we at least have the original
        if 'full_webp' not in results:
            results['full_webp'] = image_bytes
        if 'preview_webp' not in results:
            results['preview_webp'] = image_bytes
            
    return results

def _generate_ai_xmp(metadata: Dict[str, Any]) -> bytes:
    """
    Generates an XMP metadata packet following IPTC 2025.1 and C2PA-compatible standards.
    This includes machine-readable signals for AI-generated content.
    """
    prompt = str(metadata.get("prompt") or "")
    model = str(metadata.get("model") or "Unknown AI")
    software = str(metadata.get("software") or "OpenMates")
    source = str(metadata.get("source") or "OpenMates AI")
    creator = str(metadata.get("creator") or "OpenMates")
    generated_at = str(metadata.get("generated_at") or "")

    # Define namespaces
    # Note: IPTC 2025.1 uses the Iptc4xmpExt namespace for AI properties
    xmp_ns = {
        'x': 'adobe:ns:meta/',
        'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
        'dc': 'http://purl.org/dc/elements/1.1/',
        'xmp': 'http://ns.adobe.com/xap/1.0/',
        'iptcAI': 'http://iptc.org/std/Iptc4xmpExt/2021/metadata/',
        'photoshop': 'http://ns.adobe.com/photoshop/1.0/'
    }

    # Register namespaces to avoid ns0: prefix
    for prefix, uri in xmp_ns.items():
        ET.register_namespace(prefix, uri)

    # Build XML structure
    xmpmeta = ET.Element('{%s}xmpmeta' % xmp_ns['x'], {
        '{%s}xmptk' % xmp_ns['x']: 'Adobe XMP Core 5.6-c140'
    })
    
    rdf = ET.SubElement(xmpmeta, '{%s}RDF' % xmp_ns['rdf'])
    description = ET.SubElement(rdf, '{%s}Description' % xmp_ns['rdf'], {
        '{%s}about' % xmp_ns['rdf']: '',
        # DigitalSourceType is the core "AI-generated" signal (IPTC/C2PA standard)
        '{%s}DigitalSourceType' % xmp_ns['iptcAI']: 'http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia',
        '{%s}aiSystemUsed' % xmp_ns['iptcAI']: model,
        '{%s}aiPromptInformation' % xmp_ns['iptcAI']: prompt,
        '{%s}CreatorTool' % xmp_ns['xmp']: software,
        '{%s}Source' % xmp_ns['photoshop']: source,
        '{%s}Credit' % xmp_ns['photoshop']: 'OpenMates',
    })

    # Add Dublin Core fields
    dc_creator = ET.SubElement(description, '{%s}creator' % xmp_ns['dc'])
    seq = ET.SubElement(dc_creator, '{%s}Seq' % xmp_ns['rdf'])
    li = ET.SubElement(seq, '{%s}li' % xmp_ns['rdf'])
    li.text = creator

    dc_description = ET.SubElement(description, '{%s}description' % xmp_ns['dc'])
    alt = ET.SubElement(dc_description, '{%s}Alt' % xmp_ns['rdf'])
    li_desc = ET.SubElement(alt, '{%s}li' % xmp_ns['rdf'], {
        '{%s}lang' % 'http://www.w3.org/XML/1998/namespace': 'x-default'
    })
    # Include prompt in description so it's visible in macOS Preview and other viewers
    # Using multi-line format for better readability
    li_desc.text = f"AI-generated on OpenMates\nModel: {model}\nGenerated at: {generated_at}\nPrompt: {prompt}"

    # Add prompt as a separate title field
    dc_title = ET.SubElement(description, '{%s}title' % xmp_ns['dc'])
    alt_title = ET.SubElement(dc_title, '{%s}Alt' % xmp_ns['rdf'])
    li_title = ET.SubElement(alt_title, '{%s}li' % xmp_ns['rdf'], {
        '{%s}lang' % 'http://www.w3.org/XML/1998/namespace': 'x-default'
    })
    li_title.text = prompt

    # Add prompt to subject (Keywords) for better searchability
    dc_subject = ET.SubElement(description, '{%s}subject' % xmp_ns['dc'])
    bag = ET.SubElement(dc_subject, '{%s}Bag' % xmp_ns['rdf'])
    li_subj1 = ET.SubElement(bag, '{%s}li' % xmp_ns['rdf'])
    li_subj1.text = "AI-generated"
    li_subj2 = ET.SubElement(bag, '{%s}li' % xmp_ns['rdf'])
    li_subj2.text = "OpenMates"
    if prompt:
        li_subj3 = ET.SubElement(bag, '{%s}li' % xmp_ns['rdf'])
        li_subj3.text = prompt

    # Add generated date if available
    if generated_at:
        create_date = ET.SubElement(description, '{%s}CreateDate' % xmp_ns['xmp'])
        create_date.text = generated_at

    # Convert to string and wrap in XMP processing instructions
    xml_str = ET.tostring(xmpmeta, encoding='utf-8').decode('utf-8')
    
    # Standard XMP wrapping
    xmp_packet = (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        f'{xml_str}\n'
        '<?xpacket end="w"?>'
    ).encode('utf-8')

    return xmp_packet
