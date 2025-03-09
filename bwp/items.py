# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy


class PdfItem(scrapy.Item):
    name = scrapy.Field()
    link_args = scrapy.Field()


class ExcelItem(scrapy.Item):
    name = scrapy.Field()
    link_args = scrapy.Field()


class PostingItem(scrapy.Item):
    index = scrapy.Field()
    posting_date = scrapy.Field()

    pdf = scrapy.Field(serializer=PdfItem)
    excel = scrapy.Field(serializer=ExcelItem)


class CheckSum(scrapy.Item):
    value = scrapy.Field()
