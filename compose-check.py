#!/usr/bin/python3

import click
import datetime
import jinja2
import json
import logging
import os
import pprint
import re
import urllib.request
import yaml

from bs4 import BeautifulSoup as Soup
from copy import deepcopy


logger = logging.getLogger(__name__)
SCRIPTPATH = os.path.dirname(os.path.realpath(__file__))


def get_compose_ids(composes_url, name, version):
    """
    Return list with IDs of available composes

    :param composes_url: top level URL containing composes
    :param name: OS name for which to return composes
    :param version: OS version for which to return composes
    :return: ordered list of compose IDs, from newest to oldest
    """

    compose_re = re.compile(
        "^({name}-{version}-[^/]*)".format(name=name, version=version)
    )

    weburl = urllib.request.urlopen(composes_url)
    html = weburl.read()
    soup = Soup(html, "html.parser")

    comp_links = soup.find_all("a", href=compose_re)

    ids = []
    for link in comp_links:
        match = re.search(compose_re, link["href"])
        group = match.group()
        ids.append(group)

    return sorted(ids, key=str.lower, reverse=True)


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
    help="YAML input file containing status from previous check",
    type=click.Path(exists=True, readable=True),
)
@click.option(
    "--output",
    help="YAMl output file to contain status from this check",
    type=click.Path(writable=True),
    default="status.yaml",
)
@click.option(
    "--html",
    help="HTML Output file to contain status from this check",
    type=click.Path(writable=True),
    # default="status.html",
)
def cli(debug, url, name, version, input, output, html):
    # alternate: --url "https://composes.stream.centos.org/production" --name "CentOS-Stream" --version "9"

    if debug:
        logging.basicConfig(format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")
        logger.setLevel(logging.DEBUG)
        logger.debug("Debugging mode enabled")
    else:
        logging.basicConfig(level=logging.INFO)

    now = datetime.datetime.now()
    today = now.date()

    results = {}
    results["today"] = str(today)
    results["now"] = now.strftime("%Y-%m-%d %H:%M:%S")

    logger.debug("Today is {}".format(results["today"]))
    logger.debug("Now is {}".format(results["now"]))

    old_results = None
    if input:
        with open(input, "r") as f:
            old_results = yaml.safe_load(f)
        logger.info("old YAML results loaded from {}".format(input))
        logger.debug("old_results = {}".format(pprint.pformat(old_results)))

    results["composes"] = []

    result = {}
    result["url"] = url
    result["name"] = name
    result["version"] = version
    result["description"] = "{}-{} composes".format(name, version)

    result["latest_attempted"] = {}
    result["latest_finished"] = {}
    result["latest_incomplete"] = {}

    logger.info(f"For {url = }, {name = }, {version = }")
    ids = get_compose_ids(url, name, version)
    # Note: list of compose IDs is ordered from newest to oldest
    for id in ids:
        logger.debug("Getting status for compose = {}".format(id))
        status, date = compose_status(url, id)
        if date is None:
            logger.debug("No date, extracting from compose name {}".format(id))
            date_re = re.compile(
                "^{name}-{version}-(\d{{8}})\..*$".format(name=name, version=version)
            )
            match = re.search(date_re, id)
            if match:
                date = match.group(1)
                logger.debug("Extracted date {} from compose name {}".format(date, id))
            else:
                logger.notice("Cannot extract date from compose name {}".format(id))
                next

        parsed_date = datetime.datetime.strptime(date, "%Y%m%d").date()
        age = (today - parsed_date).days
        logger.info(
            "Compose {} status = {} date = {} age = {}".format(id, status, date, age)
        )
        comp_info = {
            "id": id,
            "url": "{}/{}/".format(url, id),
            "status": status,
            "date": date,
            "age": age,
        }

        if not result["latest_attempted"]:
            result["latest_attempted"] = deepcopy(comp_info)

        if status == "FINISHED" and not result["latest_finished"]:
            result["latest_finished"] = deepcopy(comp_info)

        if status == "FINISHED_INCOMPLETE" and not result["latest_incomplete"]:
            result["latest_incomplete"] = deepcopy(comp_info)

    results["composes"].append(result)

    logger.debug("results = {}".format(pprint.pformat(results)))

    if output:
        with open(output, "w") as f:
            yaml.safe_dump(results, f)
        logger.info("YAML results saved to {}".format(output))

    if html:
        j2_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(searchpath=SCRIPTPATH)
        )
        tmpl = j2_env.get_template("status.html.j2")
        tmpl.stream(results=results).dump(html)
        logger.info("HTML results written to {}".format(html))


if __name__ == "__main__":
    cli()
