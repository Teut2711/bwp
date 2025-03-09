import mimetypes
import re
import time
import scrapy
import json
import os


class BWPipelinesSpider(scrapy.Spider):
    """
    Spider for scraping and downloading files from bwpipelines.com.

    This spider crawls through paginated tables containing PDF and Excel files,
    downloads them, and stores metadata in a JSON file. It handles pagination,
    file downloads with proper delays, and maintains a structured record of all
    downloaded content.

    Attributes:
        name (str): Identifier for the spider
        allowed_domains (list): List of domains the spider is allowed to crawl
        start_urls (list): Initial URL to begin crawling
        output_json_file (str): Path where metadata JSON will be saved
        download_folder (str): Directory where downloaded files are stored
        page_index (int): Current page being processed
    """

    name = "bwpipelines"
    allowed_domains = ["infopost.bwpipelines.com"]
    start_urls = [
        "https://infopost.bwpipelines.com/Posting/default.aspx?Mode=Display&Id=11&tspid=1"
    ]
    output_json_file = "metadata.json"
    download_folder = "downloads"
    page_index = 1

    def __init__(self, from_page=2, to_page=3, *args, **kwargs):
        """
        Initialize the spider with page range configuration and setup.

        Args:
            from_page (int, optional): Starting page number for crawling. Defaults to 2.
            to_page (int, optional): Ending page number for crawling. Defaults to 3.
            *args: Additional positional arguments passed to parent class
            **kwargs: Additional keyword arguments passed to parent class
        """
        super().__init__(*args, **kwargs)
        self.from_page = int(from_page) if from_page else 2
        self.to_page = int(to_page) if to_page else 3

        os.makedirs(self.download_folder, exist_ok=True)

        self.metadata = []

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

        hidden_inputs = response.xpath("//input[@type='hidden']")
        form_data = {
            field.attrib["name"]: field.attrib.get("value", "")
            for field in hidden_inputs
        }

        if self.from_page <= self.page_index < self.to_page:
            table_rows = response.xpath(
                "//table[@id='dgITMatrix']/tr[starts-with(@id, 'dgITMatrix_')]"
            )

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

                if excel_link:
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

                if pdf_link:
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

        # Extract filename from headers
        content_disposition = response.headers.get("Content-Disposition", b"").decode()
        file_name = None

        if "filename=" in content_disposition:
            file_name = re.search(
                r'filename\*?=["\']?(?:UTF-8\'\')?([^"\']+)', content_disposition
            )
            file_name = file_name.group(1) if file_name else None

        # If filename is not found in headers, fall back to meta
        if not file_name:
            file_name = response.meta.get("file_name", "downloaded_file")

        # Remove invalid characters (e.g., `/`, `\`, `:`, `?`)
        file_name = re.sub(r'[\\/:"*?<>|]', "_", file_name)

        # Ensure correct file extension based on content type
        content_type = response.headers.get("Content-Type", b"").decode()
        if not os.path.splitext(file_name)[1]:  # If no extension in filename
            ext = mimetypes.guess_extension(content_type.split(";")[0])
            if ext:
                file_name += ext

        file_path = os.path.join(self.download_folder, file_name)

        with open(file_path, "wb") as f:
            f.write(response.body)

        self.logger.info(f"Downloaded file: {file_path}")

    def _save_metadata(self):
        """
        Save collected metadata to JSON file.

        Writes the current state of self.metadata to the configured output file
        in a formatted JSON structure with UTF-8 encoding.
        """

        with open(self.output_json_file, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=4)
        self.logger.info(f"Metadata saved to {self.output_json_file}")

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
