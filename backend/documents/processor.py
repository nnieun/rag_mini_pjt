import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
import pytesseract


SUPPORTED_TYPES = {
    "application/pdf",
    "text/plain",
    "application/xml",
    "text/xml",
    "image/png",
    "image/jpeg",
}


@dataclass
class ExtractedDocument:
    filename: str
    media_type: str
    text: str
    pages: int
    extraction_method: str


def _ocr_image(data: bytes, language: str = "kor+eng") -> str:
    image = Image.open(io.BytesIO(data))
    image.verify()
    image = Image.open(io.BytesIO(data)).convert("RGB")
    try:
        return pytesseract.image_to_string(image, lang=language).strip()
    except pytesseract.TesseractNotFoundError as error:
        raise ValueError(
            "이미지 OCR을 사용하려면 시스템에 Tesseract OCR을 설치해야 합니다."
        ) from error


def extract_document(
    filename: str,
    media_type: str,
    data: bytes,
    *,
    max_bytes: int = 10 * 1024 * 1024,
) -> ExtractedDocument:
    if not data:
        raise ValueError("빈 파일은 처리할 수 없습니다.")
    if len(data) > max_bytes:
        raise ValueError(f"파일 크기는 {max_bytes // (1024 * 1024)}MB 이하여야 합니다.")
    if media_type not in SUPPORTED_TYPES:
        suffix = Path(filename).suffix.lower()
        media_type = {
            ".pdf": "application/pdf",
            ".txt": "text/plain",
            ".xml": "application/xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }.get(suffix, media_type)
    if media_type not in SUPPORTED_TYPES:
        raise ValueError("PDF, TXT, XML, PNG, JPEG 파일만 지원합니다.")

    if media_type.startswith("text/") or media_type == "application/xml":
        text = data.decode("utf-8-sig").strip()
        method, pages = "text", 1
    elif media_type.startswith("image/"):
        text = _ocr_image(data)
        method, pages = "ocr", 1
    else:
        reader = PdfReader(io.BytesIO(data))
        parts = [(page.extract_text() or "").strip() for page in reader.pages]
        text = "\n\n".join(part for part in parts if part)
        method, pages = "pdf_text", len(reader.pages)
        if not text:
            raise ValueError(
                "텍스트가 없는 스캔 PDF입니다. 페이지 이미지 OCR 변환이 필요합니다."
            )

    if not text:
        raise ValueError("문서에서 텍스트를 추출하지 못했습니다.")
    return ExtractedDocument(filename, media_type, text, pages, method)
