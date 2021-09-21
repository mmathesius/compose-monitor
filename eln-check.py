#!/usr/bin/python3

import click
import datetime
import json
import logging
import re
import urllib.request

from bs4 import BeautifulSoup as Soup


logger = logging.getLogger(__name__)


def get_composes(composes_url, name="Fedora-ELN", version="Rawhide"):
    """
    Return list of available composes

    :param composes_url: top level URL containing composes
    :param name: OS name for which to return composes
    :param version: OS version for which to return composes
    :return: ordered list of composes, from newest to oldest
    """

    compose_re = re.compile(
        "^({name}-{version}-[^/]*)".format(name=name, version=version)
    )

    weburl = urllib.request.urlopen(composes_url)
    html = weburl.read()
    soup = Soup(html, "html.parser")

    comp_links = soup.find_all("a", href=compose_re)

    comps = []
    for link in comp_links:
        match = re.search(compose_re, link["href"])
        group = match.group()
        comps.append(group)

    return sorted(comps, key=str.lower, reverse=True)


def compose_status(composes_url, compose):
    """
    Fetch the status of the specified compose.

    :param composes_url: top level URL containing composes
    :param compose: the compose for which to fetch the status
    :return: 2-tuple of the form (status, date) where
             status is None, 'FINISHED', 'FINISHED_INCOMPLETE', etc.
             and date is None or a string in the form of YYYYMMDD
    """

    try:
        weburl = urllib.request.urlopen("{}/{}/STATUS".format(composes_url, compose))
        data = weburl.read()
        encoding = weburl.info().get_content_charset("utf-8")
        status = data.decode(encoding).rstrip()
    except Exception:
        status = None

    try:
        weburl = urllib.request.urlopen(
            "{}/{}/compose/metadata/composeinfo.json".format(composes_url, compose)
        )
        data = weburl.read()
        encoding = weburl.info().get_content_charset("utf-8")
        composeattrs = json.loads(data.decode(encoding))
        composedate = composeattrs["payload"]["compose"]["date"]
    except Exception:
        composedate = None

    return status, composedate


@click.command()
@click.option(
    "--debug",
    is_flag=True,
    help="Output a lot of debugging information",
    show_default=True,
    default=False,
)
@click.option(
    "--url",
    help="Top level URL containing composes",
    show_default=True,
    default="https://odcs.fedoraproject.org/composes/production",
)
@click.option(
    "--name",
    help="OS name for which to check composes",
    show_default=True,
    default="Fedora-ELN",
)
@click.option(
    "--version",
    help="OS version for which to check composes",
    show_default=True,
    default="Rawhide",
)
@click.option(
    "--input",
    help="Input file containing status from previous check",
    type=click.Path(exists=True, readable=True),
)
@click.option(
    "--output",
    help="Output file to contain status from this check",
    type=click.Path(writable=True),
)
def cli(debug, url, name, version, input, output):
    # alternate: --url "https://composes.stream.centos.org/production" --name "CentOS-Stream" --version "9"

    if debug:
        logging.basicConfig(format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")
        logger.setLevel(logging.DEBUG)
        logger.debug("Debugging mode enabled")
    else:
        logging.basicConfig(level=logging.INFO)

    now = datetime.datetime.now()
    today = now.date()

    logger.debug("Today is {}".format(str(today)))
    logger.debug("Now is {}".format(now.strftime("%Y-%m-%d %H:%M:%S")))

    latest_attempted = {"compose": None, "date": None}
    latest_finished = {"compose": None, "date": None}
    latest_incomplete = {"compose": None, "date": None}

    logger.info(f"For {url = }, {name = }, {version = }")
    composes = get_composes(url, name, version)
    # Note: list of composes is ordered from newest to oldest
    for c in composes:
        logger.debug("Getting status for compose = {}".format(c))
        status, date = compose_status(url, c)
        if date is None:
            logger.debug("No date, extracting from compose name {}".format(c))
            date_re = re.compile(
                "^{name}-{version}-(\d{{8}})\..*$".format(name=name, version=version)
            )
            match = re.search(date_re, c)
            if match:
                date = match.group(1)
                logger.debug("Extracted date {} from compose name {}".format(date, c))
            else:
                logger.notice("Cannot extract date from compose name {}".format(c))
                next

        parsed_date = datetime.datetime.strptime(date, "%Y%m%d").date()
        age = (today - parsed_date).days
        logger.info(
            "Compose {} status = {} date = {} age = {}".format(c, status, date, age)
        )
        # if latest_attempt["compose"] is None:


if __name__ == "__main__":
    cli()
