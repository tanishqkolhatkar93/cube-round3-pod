"""Deterministic QR decoding tier (Tier-1 SKU evidence) via OpenCV.

Replaces pyzbar, which required a system zbar DLL (libzbar-64.dll /
msvcr120.dll) that is unavailable on some Windows hosts and needs
libzbar0 on Linux. OpenCV is pip-only and works everywhere.

Accepted limitation (documented): OpenCV's detector reads QR codes only,
NOT 1D barcodes. 1D retail barcodes (UPC/EAN) were already deliberately
ignored by the SKU check — we cannot map retail barcodes to SKUs without
a catalogue — so this loses nothing.

The tier must never crash the pipeline: any failure returns [].
"""
import logging

log = logging.getLogger("rcv.barcode")

try:
    import cv2
    import numpy as np
    _AVAILABLE = True
except Exception as e:            # ImportError or missing native lib
    cv2 = None                    # type: ignore
    np = None                     # type: ignore
    _AVAILABLE = False
    log.warning("OpenCV unavailable (%s); QR tier disabled", e)


def barcode_available() -> bool:
    return _AVAILABLE


def _texts_from(img) -> list:
    """Multi-QR first (one photo may contain several payloads); falls back
    to the single-QR API. Both are local and deterministic."""
    try:
        ok, infos, _pts, _q = cv2.QRCodeDetector().detectAndDecodeMulti(img)
        if ok:
            return [t for t in infos if t]
    except Exception:
        pass
    try:
        data, _pts, _q = cv2.QRCodeDetector().detectAndDecode(img)
        return [data] if data else []
    except Exception:
        return []


def decode_barcodes(jpeg_bytes: bytes) -> list:
    """Distinct decoded QR payloads. Never raises; failures return []."""
    if not _AVAILABLE or not jpeg_bytes:
        return []
    try:
        img = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return []
        out = []
        for text in _texts_from(img):
            text = (text or "").strip()
            if text and text not in out:
                out.append(text)
        return out
    except Exception as e:
        log.warning("QR decode failed: %s", e)
        return []