"""
Interact with your school website with telegram!

Copyright (c) 2016-2018 Paolo Barbolini <paolo@paolo565.org>
Released under the MIT license
"""

from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urlparse
import urllib

import os
import requests
import subprocess


def prettify_page(page_url, html):
    parsed_html = BeautifulSoup(html, "html.parser")

    # Find all images
    for img in parsed_html.find_all("img"):
        img["src"] = urllib.parse.urljoin(page_url, img["src"])

    # Remove the default styles
    for p in parsed_html.find_all("style"):
        p.decompose()

    # Custom css
    custom_style = parsed_html.new_tag("style")
    custom_style.string = """
        * {
            font-weight: bold;
            text-decoration: none;
            text-transform: uppercase;
            font-family: 'Designosaur';
            font-size: 9pt;
        }

        .nodecBlack {
            color: #000000;
        }

        .nodecWhite {
            color: #FFFFFF;
        }

        td {
            padding: 10px;
        }

        center:first-of-type,
        center:last-of-type,
        .mathema p,
        #mathema {
            display: none;
        }

        .nodecBlack, .nodecWhite {
          max-height: 20px;
        }

         #nodecBlack, #nodecWhite {
          height: 10px;
          max-height: 10px;
        }

        p {
          margin: 0;
          margin-top: 5px;
          padding: 0;
        }
    """
    parsed_html.html.head.contents.insert(0, custom_style)

    return str(parsed_html)


def send_page(db, bot, message, page, caption):
    # Did we check if the page changed in the last hour?
    if page.last_check is not None and \
       (datetime.utcnow() - page.last_check).seconds < 3600:
        message.reply_with_photo(file_id=page.last_file_id, caption=caption)
        return

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TelegramSchoolBot/2.0; "
                      "+https://github.com/paolobarbolini/TelegramSchoolBot)",
    }

    # Add the If-Modified-Since header if we have an already cached image.
    # With this header if the file didn't change since the last check
    # the server will reply with a 304 response code
    if page.last_update is not None:
        nowstr = page.last_update.strftime("%a, %d %b %Y %H:%M:%S GMT")
        headers["If-Modified-Since"] = nowstr

    response = requests.get(page.url, headers=headers)
    if response.status_code != 200 and response.status_code != 304:
        raise ValueError("Got %i from %s" % (response.status_code, page.url))

    session = db.Session()

    # This is required because the page object is generated by another session
    # and sqlalchemy doesn't like objects attached to another session
    session = session.object_session(page)

    if response.status_code == 304:
        # The page didn't change, send a cached photo and update the last_check
        message.reply_with_photo(file_id=page.last_file_id, caption=caption)

        page.last_check = datetime.utcnow()
        session.commit()
        return

    # The page did change, prepare the html file for wkhtmltoimage
    html_path = "/tmp/tsb-body-%i.html" % page.id
    prettified_body = prettify_page(page.url, response.text)
    with open(html_path, "w") as f:
        f.write(prettified_body)

    # Render the html file into a jpeg image
    # (png is a waste because telegram compresses the image)
    image_path = "/tmp/tsb-image-%i.jpeg" % page.id
    subprocess.call(("xvfb-run", "wkhtmltoimage",
                     "--format", "jpeg", "--quality", "100",
                     html_path, image_path))

    message = message.reply_with_photo(path=image_path, caption=caption)

    # Update the database with the new telegram file id and the last time
    # we checked for changes
    page.last_file_id = message.photo.file_id
    page.last_check = page.last_update = datetime.utcnow()
    session.commit()

    # Remove the temporary files
    os.remove(html_path)
    os.remove(image_path)


def shorten_url(url):
    domain = urlparse(url).netloc

    if domain.startswith("www."):
        domain = domain[4:]

    return domain
