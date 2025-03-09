import re
import time
import httpx
import scrapy
import json
import os


class PipelinesSpider(scrapy.Spider):
    name = "pipelines"
    allowed_domains = ["infopost.bwpipelines.com"]
    start_urls = [
        "https://infopost.bwpipelines.com/Posting/default.aspx?Mode=Display&Id=11&tspid=1"
    ]
    output_json_file = "metadata.json"
    download_folder = "downloads"
    page_index = 0

    def __init__(self, from_page=2, to_page=3, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.from_page = int(from_page) if from_page else 2
        self.to_page = int(to_page) if to_page else 3  # Default to 3

        self.download_folder = "downloads"
        os.makedirs(self.download_folder, exist_ok=True)

        self.metadata = []
        self.client = httpx.AsyncClient()

    def parse(self, response):
        """Parse the first page and extract table data."""

        hidden_inputs = response.xpath("//input[@type='hidden']")
        form_data = {
            field.attrib["name"]: field.attrib.get("value", "")
            for field in hidden_inputs
        }

        table_rows = response.xpath(
            "//table[@id='dgITMatrix']/tr[starts-with(@id, 'dgITMatrix_')]"
        )

        if self.from_page <= self.page_index < self.to_page:

            for index, row in enumerate(table_rows, start=1):
                pdf_link = row.xpath(".//td[1]//a/@href").get()
                pdf_link = response.urljoin(pdf_link) if pdf_link else None
                pdf_name = self._get_file_name(row, ".//td[1]//a")

                upload_date = row.xpath(".//td[2]//text()").get()
                upload_date = upload_date.strip() if upload_date else None

                excel_link = row.xpath(".//td[3]//a/@href").get()
                excel_link = response.urljoin(excel_link) if excel_link else None
                excel_name = self._get_file_name(row, ".//td[3]//a")

                pdf_args = self._extract_link_args(pdf_link)
                excel_args = self._extract_link_args(excel_link)
                entry = {
                    "index": index,
                    "pdf": {
                        "name": pdf_name,
                        "link_args": pdf_args,
                    },
                    "upload_date": upload_date,
                    "excel": {
                        "name": excel_name,
                        "link_args": excel_args,
                    },
                }

                self.metadata.append(entry)

                # Download PDF (if available)
                if pdf_link:
                    time.sleep(5)  # Enzforce 5-second delay before download
                    yield scrapy.FormRequest(
                        url=response.url,
                        formdata={
                            **form_data,
                            "__EVENTTARGET": excel_args[0],
                            "__EVENTARGUMENT": excel_args[1],
                        },
                        callback=self._download_file,
                        meta={"file_name": excel_name},
                    )

                # Download Excel (if available)
                if excel_link:
                    time.sleep(5)  # Enforce 5-second delay before download
                    yield scrapy.FormRequest(
                        url=response.url,
                        formdata={
                            **form_data,
                            "__EVENTTARGET": pdf_args[0],
                            "__EVENTARGUMENT": pdf_args[1],
                        },
                        callback=self._download_file,
                        meta={"file_name": pdf_name},
                    )
        self._save_metadata()

        next_page_href = response.xpath(
            "//table[@id='dgITMatrix']//tr[1]//a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'next')]/@href"
        ).get()

        next_page_args = self._extract_link_args(next_page_href)
        form_data["__EVENTTARGET"] = next_page_args[0]
        form_data["__EVENTARGUMENT"] = next_page_args[1]

        self.page_index += 1
        yield scrapy.FormRequest(
            url=response.url,
            formdata=form_data,
            callback=self.parse,
        )

    def _download_file(self, response):
        """Download files (PDF/Excel) and save them locally, ensuring a valid filename."""
        file_name = response.meta.get("file_name", "downloaded_file")

        # Remove invalid characters (e.g., `/`, `\`, `:`)
        file_name = re.sub(r'[\\/:"*?<>|]', "_", file_name)

        file_path = os.path.join(self.download_folder, file_name)

        with open(file_path, "wb") as f:
            f.write(response.body)

        self.logger.info(f"Downloaded file: {file_path}")

    def _save_metadata(self):
        """Write metadata to a JSON file."""
        with open(self.output_json_file, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=4)
        self.logger.info(f"Metadata saved to {self.output_json_file}")

    def _get_file_name(self, element, xpath_base):
        """Helper method to join text and class attributes."""
        text = (element.xpath(f"{xpath_base}/text()").get() or "").strip()
        class_name = (element.xpath(f"{xpath_base}/@class").get() or "").strip()
        return ".".join(filter(None, [text, class_name]))

    def _extract_link_args(self, js_link):
        """Extracts arguments from WebForm_PostBackOptions or __doPostBack."""
        if not js_link:
            return []

        match = re.search(
            r"javascript:WebForm_DoPostBackWithOptions\(new WebForm_PostBackOptions\((.*)\)\)",
            js_link,
        )
        if not match:
            match = re.search(r"javascript:__doPostBack\((.*)\)", js_link)

        args = []
        if match:
            args = [arg.strip("\"' ") for arg in match.group(1).split(",")]

        return args
