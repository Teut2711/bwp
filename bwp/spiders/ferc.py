import re
import scrapy

from bwp.items import CheckSum


class FercSpider(scrapy.Spider):
    name = "ferc"
    allowed_domains = ["forms.ferc.gov"]
    start_urls = ["https://forms.ferc.gov"]
    custom_settings = {
        "FEEDS": {
            "ferc_output.csv": {
                "format": "csv",
                "encoding": "utf8",
                "store_empty": False,
                "overwrite": True,
            }
        }
    }

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

        form_view_link = response.xpath(
            "//table[@id='tableLeftMenu']//td[@id='item1Data']//a/@href"
        ).get()
        form_view_args = self._extract_link_args(form_view_link)

        yield scrapy.FormRequest(
            url=response.url,
            formdata={
                **form_data,
                "__EVENTTARGET": form_view_args[0],
                "__EVENTARGUMENT": form_view_args[1],
                "ctl00$Content1$HomeBtnClicked": "0",
                "ctl00$Content1$FormSubmExeName": "",
                "ctl00$Content1$FormViewExeName": "",
                "ctl00$ItemIndex": "1",
            },
            callback=self._scrap_checksum,
        )

    def _scrap_checksum(self, response):
        checksum = response.xpath(
            "//textarea[@name='ctl00$Content1$txtFormViewSHA256']/text()"
        ).get()
        if checksum:

            yield CheckSum(value=checksum.strip("\r\n \"'"))  # may use itemloader

            self.log("Checksum saved")

        else:
            self.log("Checksum not found on the page")

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

        match = re.search(r"javascript:__doPostBack\((.*)\)", js_code)

        args = []
        if match:
            args = [arg.strip("\"' ") for arg in match.group(1).split(",")]

        return args
