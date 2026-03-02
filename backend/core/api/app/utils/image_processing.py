# backend/core/api/app/utils/image_processing.py
#
# Image processing utilities for format conversion and thumbnail generation.
# Uses Pillow for high-performance image manipulation.
# Includes industry-standard AI content labeling via IPTC 2025.1 and C2PA-compatible metadata.
#
# SVG support:
# When output_filetype="svg" is requested, use process_svg_for_storage() instead of
# process_image_for_storage(). SVGs are stored as-is (raw XML bytes) for the "original"
# format, and rasterized to a WEBP preview via cairosvg for inline display in chat.

import logging
import io
import xml.etree.ElementTree as ET
from typing import Tuple, Dict, Any, Optional
from PIL import Image
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
import datetime

try:
    import c2pa
    HAS_C2PA = True
except ImportError:
    HAS_C2PA = False

logger = logging.getLogger(__name__)

# Cache for C2PA credentials to avoid re-generating
_C2PA_CERTS: Optional[Tuple[bytes, bytes, Any]] = None

def _ensure_c2pa_credentials() -> Tuple[bytes, bytes, Any]:
    """
    Ensures that we have a self-signed certificate and private key for C2PA signing.
    In a production environment, these should be loaded from Vault or environment variables.
    """
    global _C2PA_CERTS
    if _C2PA_CERTS:
        return _C2PA_CERTS

    # Generate EC key for ES256
    key = ec.generate_private_key(ec.SECP256R1())

    # Generate certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"California"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"OpenMates"),
        x509.NameAttribute(NameOID.COMMON_NAME, u"OpenMates AI Signer"),
    ])
    
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow() - datetime.timedelta(days=1)
    ).not_valid_after(
        # 10 years
        datetime.datetime.utcnow() + datetime.timedelta(days=3650)
    ).add_extension(
        x509.BasicConstraints(ca=False, path_length=None), critical=True,
    ).add_extension(
        x509.KeyUsage(
            digital_signature=True,
            content_commitment=False,
            key_encipherment=False,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=False,
            crl_sign=False,
            encipher_only=False,
            decipher_only=False
        ), critical=True
    ).add_extension(
        x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
        critical=False
    ).add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),
        critical=False
    ).add_extension(
        x509.ExtendedKeyUsage([
            x509.oid.ExtendedKeyUsageOID.EMAIL_PROTECTION,
            x509.ObjectIdentifier("1.3.6.1.4.1.597.11.1"), # c2pa signing
        ]), critical=False
    ).sign(key, hashes.SHA256())

    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
    key_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )

    _C2PA_CERTS = (cert_bytes, key_bytes, key)
    return _C2PA_CERTS

def _apply_c2pa_signing(image_bytes: bytes, metadata: Dict[str, Any], img_format: str) -> bytes:
    """
    Apply C2PA manifest signing to the image bytes.
    """
    if not HAS_C2PA:
        return image_bytes

    try:
        cert_bytes, key_bytes, key = _ensure_c2pa_credentials()
        
        # Build manifest
        manifest = {
            "claim_generator": f"OpenMates/{metadata.get('software', '1.0')}",
            "assertions": [
                {
                    "label": "c2pa.training-mining",
                    "data": {
                        "entries": {
                            "c2pa.ai_generative": {"status": "constrained"},
                            "c2pa.ai_training": {"status": "constrained"}
                        }
                    }
                },
                {
                    "label": "staxel.ai_metadata",
                    "data": {
                        "model": metadata.get("model", "Unknown AI"),
                        "prompt": metadata.get("prompt", ""),
                        "generated_at": metadata.get("generated_at", datetime.datetime.utcnow().isoformat())
                    }
                },
                {
                    "label": "c2pa.digital_source_type",
                    "data": "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
                }
            ]
        }
        
        # Sign using a callback to avoid ta_url issues and support ES256 properly
        def signing_callback(data: bytes) -> bytes:
            return key.sign(
                data,
                ec.ECDSA(hashes.SHA256())
            )

        signer = c2pa.Signer.from_callback(
            signing_callback,
            c2pa.C2paSigningAlg.ES256,
            cert_bytes.decode('utf-8')
        )
        
        # Create a builder
        builder = c2pa.Builder(manifest)
        
        # Sign the bytes
        mime_type = f"image/{img_format.lower()}"
        if img_format.lower() == "webp":
            mime_type = "image/webp"
            
        # sign(signer, format, source, dest)
        source_stream = io.BytesIO(image_bytes)
        dest_stream = io.BytesIO()
        builder.sign(signer, mime_type, source_stream, dest_stream)
        
        return dest_stream.getvalue()
        
    except Exception as e:
        logger.error(f"C2PA signing failed: {e}", exc_info=True)
        return image_bytes

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
        orig_format = img.format or "JPEG"
        
        # Prepare XMP metadata if provided
        xmp_data = None
        if metadata:
            xmp_data = _generate_ai_xmp(metadata)
            
            # Embed XMP metadata into the original image before C2PA signing.
            # For WEBP/JPEG, Pillow supports xmp= param directly.
            # For PNG, we inject XMP via an iTXt chunk with the standard key.
            fmt_upper = orig_format.upper()
            if fmt_upper == "PNG":
                from PIL.PngImagePlugin import PngInfo
                orig_io = io.BytesIO()
                png_info = PngInfo()
                png_info.add_text("XML:com.adobe.xmp", xmp_data.decode("utf-8"), zip=False)
                img.save(orig_io, format="PNG", pnginfo=png_info)
                results['original'] = orig_io.getvalue()
            elif fmt_upper in ["JPEG", "JPG"]:
                orig_io = io.BytesIO()
                img.save(orig_io, format="JPEG", quality=98, xmp=xmp_data)
                results['original'] = orig_io.getvalue()
            elif fmt_upper == "WEBP":
                orig_io = io.BytesIO()
                img.save(orig_io, format="WEBP", quality=98, xmp=xmp_data)
                results['original'] = orig_io.getvalue()
            
            # Apply C2PA signing to original (signs the XMP-embedded version)
            if fmt_upper in ["JPEG", "JPG", "PNG", "WEBP"]:
                results['original'] = _apply_c2pa_signing(results['original'], metadata, orig_format)
        
        # 1. Generate Full-size WEBP
        full_webp_io = io.BytesIO()
        # Use higher quality (90+) for full WEBP to preserve pixel-level signals like SynthID
        img.save(full_webp_io, format="WEBP", quality=90, xmp=xmp_data)
        full_webp_bytes = full_webp_io.getvalue()
        
        # Apply C2PA signing
        if metadata:
            full_webp_bytes = _apply_c2pa_signing(full_webp_bytes, metadata, "webp")
        results['full_webp'] = full_webp_bytes
        
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
        preview_webp_bytes = preview_webp_io.getvalue()
        
        # Apply C2PA signing to preview
        if metadata:
            preview_webp_bytes = _apply_c2pa_signing(preview_webp_bytes, metadata, "webp")
        results['preview_webp'] = preview_webp_bytes
        
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

def process_svg_for_storage(
    svg_bytes: bytes,
    preview_width: int = 1200,
    webp_quality: int = 80,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, bytes]:
    """
    Process a raw SVG file for storage as an embed.

    Unlike raster images, SVGs are XML text and cannot be processed by PIL directly.
    This function produces two variants:

    1. 'original': The raw SVG bytes, stored as-is (image/svg+xml).
       This is the canonical vector asset — infinitely scalable, downloadable.

    2. 'preview_webp': A rasterized WEBP preview generated via cairosvg.
       Used for inline display in chat embeds (same role as preview_webp for raster images).
       Falls back to a blank 1x1 WEBP if cairosvg is unavailable or rasterization fails.

    No 'full_webp' variant is produced — the SVG itself IS the full-resolution asset.
    The download endpoint serves the SVG for format='original' and WEBP for format='preview'.

    Args:
        svg_bytes:     Raw SVG bytes from the Recraft API.
        preview_width: Pixel width for the rasterized preview (height auto-scaled).
        webp_quality:  WEBP compression quality for the preview (0–100).
        metadata:      Optional AI metadata dict (currently unused for SVG, reserved
                       for future XMP injection into rasterized preview).

    Returns:
        Dict with keys 'original' (SVG bytes) and 'preview_webp' (WEBP bytes).
    """
    results: Dict[str, bytes] = {"original": svg_bytes}

    try:
        import cairosvg  # type: ignore[import]

        # Rasterize SVG to PNG at the requested preview width.
        # cairosvg scales height proportionally when only output_width is given.
        png_bytes = cairosvg.svg2png(bytestring=svg_bytes, output_width=preview_width)

        # Convert the rasterized PNG to WEBP via PIL for consistent format and quality.
        img = Image.open(io.BytesIO(png_bytes))
        width, height = img.size

        # Apply the same vertical / horizontal preview sizing logic as raster images:
        # - Vertical (height > width): fixed 400px height, proportional width
        # - Horizontal / Square: crop to 600x400
        is_vertical = height > width
        if is_vertical:
            new_height = 400
            new_width = int(width * (new_height / height))
            preview_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        else:
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

        preview_io = io.BytesIO()
        preview_img.save(preview_io, format="WEBP", quality=webp_quality)  # type: ignore[possibly-undefined]
        results["preview_webp"] = preview_io.getvalue()

        logger.info(
            f"SVG processed for storage: original={len(svg_bytes)}b, "
            f"preview_webp={len(results['preview_webp'])}b"
        )

    except ImportError:
        logger.warning(
            "cairosvg not installed — SVG preview rasterization unavailable. "
            "Install cairosvg to enable WEBP preview generation for SVG files. "
            "Falling back to a minimal WEBP placeholder."
        )
        results["preview_webp"] = _make_placeholder_webp()

    except Exception as e:
        logger.error(f"Failed to rasterize SVG preview: {e}", exc_info=True)
        results["preview_webp"] = _make_placeholder_webp()

    return results


def _make_placeholder_webp() -> bytes:
    """
    Generate a minimal 1×1 transparent WEBP as a fallback preview
    when SVG rasterization is unavailable or fails.
    """
    try:
        img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="WEBP")
        return buf.getvalue()
    except Exception:
        # Absolute last resort: return a hardcoded 1x1 transparent WEBP
        return (
            b"RIFF$\x00\x00\x00WEBPVP8L\x18\x00\x00\x00/"
            b"\x00\x00\x00\x00\x88\x00\x00\xfe\x03\x00\x00\xfe"
            b"\x03\x00\x00\x00"
        )


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
