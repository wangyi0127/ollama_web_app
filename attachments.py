import re
import zipfile
from io import BytesIO
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .config import MAX_OFFICE_ARCHIVE_BYTES, MAX_OFFICE_XML_BYTES


def _read_office_xml(archive, member_name):
    info = archive.getinfo(member_name)
    if info.file_size > MAX_OFFICE_XML_BYTES:
        raise ValueError(f"Office 文档内部文件过大：{member_name}")
    return ElementTree.fromstring(archive.read(member_name))


def _extract_office_text(filename, data):
    with zipfile.ZipFile(BytesIO(data)) as archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_OFFICE_ARCHIVE_BYTES:
            raise ValueError("Office 文档解压后的内容过大。")

        if filename.lower().endswith(".docx"):
            root = _read_office_xml(archive, "word/document.xml")
            return "\n".join(
                node.text or ""
                for node in root.iter()
                if node.tag.rsplit("}", 1)[-1] == "t"
            )

        if filename.lower().endswith(".pptx"):
            slide_names = sorted(
                name
                for name in archive.namelist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            )
            parts = []
            for slide_name in slide_names:
                root = _read_office_xml(archive, slide_name)
                parts.append(
                    "\n".join(
                        node.text or ""
                        for node in root.iter()
                        if node.tag.rsplit("}", 1)[-1] == "t"
                    )
                )
            return "\n".join(parts)

        if filename.lower().endswith(".xlsx"):
            shared_strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = _read_office_xml(archive, "xl/sharedStrings.xml")
                shared_strings = [
                    "".join(
                        node.text or ""
                        for node in item.iter()
                        if node.tag.rsplit("}", 1)[-1] == "t"
                    )
                    for item in root
                ]

            sheet_names = sorted(
                name
                for name in archive.namelist()
                if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
            )
            rows = []
            for sheet_name in sheet_names:
                root = _read_office_xml(archive, sheet_name)
                for row in root.iter():
                    if row.tag.rsplit("}", 1)[-1] != "row":
                        continue
                    values = []
                    for cell in row:
                        if cell.tag.rsplit("}", 1)[-1] != "c":
                            continue
                        cell_type = cell.attrib.get("t")
                        value = next(
                            (
                                child.text or ""
                                for child in cell
                                if child.tag.rsplit("}", 1)[-1] == "v"
                            ),
                            "",
                        )
                        if cell_type == "s" and value:
                            try:
                                value = shared_strings[int(value)]
                            except (IndexError, ValueError) as exc:
                                raise ValueError(
                                    "XLSX 文档包含无效的共享字符串索引。"
                                ) from exc
                        elif cell_type == "inlineStr":
                            value = "".join(
                                node.text or ""
                                for node in cell.iter()
                                if node.tag.rsplit("}", 1)[-1] == "t"
                            )
                        values.append(value)
                    if values:
                        rows.append("\t".join(values))
            return "\n".join(rows)

    raise ValueError("不支持的 Office 文档格式。")


def extract_attachment_text(filename, data):
    if filename.lower().endswith(".txt"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError(f"无法读取 TXT 文件：{exc}") from exc
        if not text.strip():
            raise ValueError("TXT 文件内容为空。")
        return text

    if filename.lower().endswith(".pdf"):
        try:
            reader = PdfReader(BytesIO(data), strict=False)
            if reader.is_encrypted:
                raise ValueError("PDF 已加密，无法读取。")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except (PyPdfError, ValueError, EOFError) as exc:
            raise ValueError(f"无法读取 PDF：{exc}") from exc
        if not text.strip():
            raise ValueError("PDF 中没有可提取的文本（扫描版 PDF 暂不支持 OCR）。")
        return text

    try:
        text = _extract_office_text(filename, data)
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise ValueError(f"无法读取 Office 文档：{exc}") from exc
    if not text.strip():
        raise ValueError("文档中没有可提取的文本。")
    return text
