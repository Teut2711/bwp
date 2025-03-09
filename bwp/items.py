# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy


class BwpItem(scrapy.Item):
    # define the fields for your item here like:
    # name = scrapy.Field()
    pass


import re
import scrapy


class CheckSum(scrapy.Item):
    value = scrapy.Field()
