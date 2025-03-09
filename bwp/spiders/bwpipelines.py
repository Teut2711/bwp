import mimetypes
import re
import time
import scrapy
import os

from bwp import settings
from bwp.items import PostingItem, ExcelItem, PdfItem


class BWPipelinesSpider(scrapy.Spider):
    """
    Spider for scraping and downloading files from bwpipelines.com.

    Scraps the second page by defaults

    Attributes:
        name (str): Identifier for the spider
        allowed_domains (list): List of domains the spider is allowed to crawl
        start_urls (list): Initial URL to begin crawling
    """

    name = "bwpipelines"
    allowed_domains = ["infopost.bwpipelines.com"]
    start_urls = [
        "https://infopost.bwpipelines.com/Posting/default.aspx?Mode=Display&Id=11&tspid=1"
    ]

    custom_settings = {
        "FEEDS": {
            "bwpipeline.json": {
                "format": "json",
                "encoding": "utf8",
                "store_empty": False,
                "overwrite": True,
            }
        },
        "DOWNLOAD_DELAY": 5,
        "DOWNLOAD_DIR": "downloads",
    }

    def __init__(self, from_page=2, to_page=3, *args, **kwargs):
        """
        Initialize the spider with user-provided page range.
        Default is from_page=2 to_page=3(excluded)
        """
        super().__init__(*args, **kwargs)
        self.from_page = int(from_page)
        self.to_page = int(to_page)
        self.download_delay = self.custom_settings["DOWNLOAD_DELAY"]
        self.download_folder = self.custom_settings["DOWNLOAD_DIR"]

    def start_requests(self):
        start_page = 1
        url = f"https://infopost.bwpipelines.com/Posting/default.aspx?Mode=Display&Id=11&tspid=1&page={start_page}"
        yield scrapy.Request(url, callback=self.parse, meta={"page_number": start_page})

    def parse(self, response):
        """
        Parse each page and process table data for downloads.

        Extracts hidden form inputs, processes table rows to gather PDF and Excel
        file information, triggers file downloads, and handles pagination.

        Args:
            response (scrapy.http.Response): Response object containing page HTML

        Yields:
            scrapy.FormRequest: Requests for file downloads and next page navigation
        """
        page_number = response.meta.get("page_number", 1)

        hidden_inputs = response.xpath("//input[@type='hidden']")
        form_data = {
            field.attrib["name"]: field.attrib.get("value", "")
            for field in hidden_inputs
        }

        if self.from_page <= page_number < self.to_page:
            table_rows = response.xpath(
                "//table[@id='dgITMatrix']/tr[starts-with(@id, 'dgITMatrix_')]"
            )

            for index, row in enumerate(table_rows, start=1):
                pdf_link = row.xpath(".//td[1]//a/@href").get()
                pdf_link = response.urljoin(pdf_link)
                pdf_name = self._get_file_name(row, ".//td[1]//a")

                posting_date = row.xpath(".//td[2]//text()").get()
                posting_date = posting_date.strip()
                excel_link = row.xpath(".//td[3]//a/@href").get()
                excel_link = response.urljoin(excel_link)
                excel_name = self._get_file_name(row, ".//td[3]//a")

                pdf_args = self._extract_link_args(pdf_link)
                excel_args = self._extract_link_args(excel_link)

                if excel_link and settings.ALLOW_FILE_DOWNLOAD:
                    time.sleep(self.settings.get("DOWNLOAD_DELAY"))
                    excel_name = yield scrapy.FormRequest(
                        url=response.url,
                        formdata={
                            **form_data,
                            "__EVENTTARGET": excel_args[0],
                            "__EVENTARGUMENT": excel_args[1],
                        },
                        callback=self._download_file,
                    )

                if pdf_link and settings.ALLOW_FILE_DOWNLOAD:
                    time.sleep(self.settings.get("DOWNLOAD_DELAY"))
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

                pdf_item = PdfItem(
                    name=pdf_name,
                    link_args=pdf_args,
                )

                excel_item = ExcelItem(
                    name=excel_name,
                    link_args=excel_args,
                )

                item = PostingItem(
                    index=index,
                    posting_date=posting_date,
                    pdf=pdf_item,
                    excel=excel_item,
                )
                yield item

        if page_number >= self.to_page:
            return

        next_page_href = response.xpath(
            "//table[@id='dgITMatrix']//tr[1]//a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'next')]/@href"
        ).get()

        next_page_args = self._extract_link_args(next_page_href)
        form_data["__EVENTTARGET"] = next_page_args[0]
        form_data["__EVENTARGUMENT"] = next_page_args[1]

        yield scrapy.FormRequest(
            url=response.url,
            formdata=form_data,
            callback=self.parse,
            meta={"page_number": page_number + 1},
        )

    def _download_file(self, response):
        """
        Handle file download and save to local storage.

        Processes response headers to determine filename and content type,
        sanitizes filenames, and saves files to the download directory.

        Args:
            response (scrapy.http.Response): Response containing file data and headers

        Note:
            Files are saved in the download_folder directory with sanitized names
            and appropriate extensions based on content type.
        """

        content_disposition = response.headers.get("Content-Disposition", b"").decode()
        file_name = None

        if "filename=" in content_disposition:
            file_name = re.search(
                r'filename\*?=["\']?(?:UTF-8\'\')?([^"\']+)', content_disposition
            )
            file_name = file_name.group(1) if file_name else None

        if not file_name:
            file_name = response.meta.get("file_name", "downloaded_file")

        file_name = re.sub(r'[\\/:"*?<>|]', "_", file_name)

        content_type = response.headers.get("Content-Type", b"").decode()
        if not os.path.splitext(file_name)[1]:
            ext = mimetypes.guess_extension(content_type.split(";")[0])
            if ext:
                file_name += ext

        file_path = os.path.join(self.download_folder, file_name)

        with open(file_path, "wb") as f:
            f.write(response.body)

        self.logger.info(f"Downloaded file: {file_path}")
        yield file_name

    def _get_file_name(self, element, xpath_base):
        """
        Extract and combine text and class attributes for filename creation.

        Args:
            element (scrapy.Selector): Element containing the file information
            xpath_base (str): Base XPath expression for finding text and class

        Returns:
            str: Combined filename from text and class attributes, joined with dots
        """
        text = (element.xpath(f"{xpath_base}/text()").get() or "").strip()
        class_name = (element.xpath(f"{xpath_base}/@class").get() or "").strip()
        return ".".join(filter(None, [text, class_name]))

    def _extract_link_args(self, js_code):
        """
        Extract arguments from JavaScript postback functions in links.

        Parses both WebForm_PostBackOptions and __doPostBack JavaScript
        function calls to extract their arguments.

        Args:
            js_code (str): JavaScript link containing postback function call

        Returns:
            list: Extracted and cleaned arguments from the JavaScript function
                 Returns empty list if no arguments found
        """
        if not js_code:
            return []

        match = re.search(
            r"javascript:WebForm_DoPostBackWithOptions\(new WebForm_PostBackOptions\((.*)\)\)",
            js_code,
        )
        if not match:
            match = re.search(r"javascript:__doPostBack\((.*)\)", js_code)

        args = []
        if match:
            args = [arg.strip("\"' ") for arg in match.group(1).split(",")]

        return args
