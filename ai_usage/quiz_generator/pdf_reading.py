from django.core.files.uploadedfile import UploadedFile
from pypdf import PdfReader


def read_pdf(file_obj: UploadedFile) -> str:
    reader = PdfReader(file_obj)

    text = []

    for page in reader.pages:
        extracted_text = page.extract_text()
        if extracted_text:
            text.append(extracted_text)

    return "\n\n".join(text)


def check_file_size(file_obj: UploadedFile, max_mb: int = 10):
    size_mb = file_obj.size / (1024 * 1024)

    if size_mb > max_mb:
        raise ValueError(
            f"PDF too large: {size_mb:.2f} MB (limit {max_mb} MB)"
            )
