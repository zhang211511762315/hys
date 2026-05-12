from dataclasses import dataclass
from io import BytesIO

import httpx
from django.conf import settings
from PIL import Image


@dataclass(frozen=True)
class OCRResult:
    text: str
    provider: str


def ocr_image_url(url: str) -> OCRResult:
    if settings.OCR_PROVIDER != "tesseract":
        return OCRResult(text="", provider=settings.OCR_PROVIDER)
    response = httpx.get(url, timeout=httpx.Timeout(settings.FETCH_TIMEOUT_SECONDS, connect=5.0))
    response.raise_for_status()
    image = Image.open(BytesIO(response.content))
    try:
        import pytesseract

        text = pytesseract.image_to_string(image, lang=settings.TESSERACT_LANG)
    except Exception:
        text = ""
    return OCRResult(text=text.strip(), provider="tesseract")
