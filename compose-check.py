#!/usr/bin/python3

import click
import datetime
import jinja2
import json
import logging
import os
import pprint
import re
import sys
import urllib.request
import yaml

from bs4 import BeautifulSoup as Soup
from copy import deepcopy


logger = logging.getLogger(__name__)
SCRIPTPATH = os.path.dirname(os.path.realpath(__file__))


def get_compose_ids(url, name, version):
    """
    Return list of available compose IDs

    :param url: top level URL containing composes
    :param name: OS name for which to return compose IDs
    :param version: OS version for which to return compose IDs
    :return: ordered list of compose IDs, from newest to oldest
    """

    compose_re = re.compile(
        "^({name}-{version}-[^/]*)".format(name=name, version=version)
    )

    weburl = urllib.request.urlopen(url)
    html = weburl.read()
    soup = Soup(html, "html.parser")

    comp_links = soup.find_all("a", href=compose_re)

    ids = []
    for link in comp_links:
        match = re.search(compose_re, link["href"])
        group = match.group()
        ids.append(group)

    return sorted(ids, key=str.lower, reverse=True)


def get_compose_status(url, id):
    """
    Fetch the status of the specified compose.

    :param url: top level URL containing composes
    :param id: the compose ID for which to fetch the status
    :return: 2-tuple of the form (status, date) where
             status is None, 'FINISHED', 'FINISHED_INCOMPLETE', etc.
             and date is None or a string in the form of YYYYMMDD
    """

    try:
        weburl = urllib.request.urlopen("{}/{}/STATUS".format(url, id))
        data = weburl.read()
        encoding = weburl.info().get_content_charset("utf-8")
        status = data.decode(encoding).rstrip()
    except Exception:
        status = None

    try:
        weburl = urllib.request.urlopen(
            "{}/{}/compose/metadata/composeinfo.json".format(url, id)
        )
        data = weburl.read()
        encoding = weburl.info().get_content_charset("utf-8")
        composeattrs = json.loads(data.decode(encoding))
        composedate = composeattrs["payload"]["compose"]["date"]
    except Exception:
        composedate = None

    return status, composedate


def get_compose_result(url, name, version, description, today):
    """
    Return dictionary with compose status

    :param url: top level URL containing composes
    :param name: OS name for compose
    :param version: OS version for compose
    :param description: OS version for compose
    :return: dictionary with compose status
    """

    result = {}
    result["url"] = url
    result["name"] = name
    result["version"] = version
    result["description"] = (
        description if description else "{}-{} composes".format(name, version)
    )

    result["latest_attempted"] = {}
    result["latest_finished"] = {}
    result["latest_incomplete"] = {}

    logger.info(f"For {url = }, {name = }, {version = }")
    ids = get_compose_ids(url, name, version)
    # Note: list of compose IDs is ordered from newest to oldest
    for id in ids:
        logger.debug("Getting status for compose = {}".format(id))
        status, date = get_compose_status(url, id)
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

    return result


@click.command()
@click.option(
    "--debug",
    is_flag=True,
    help="Output a lot of debugging information",
    show_default=True,
    default=False,
)
@click.option(
    "--config",
    help="YAML configuration file",
    type=click.Path(exists=True, readable=True),
)
@click.option(
    "--url",
    help="Top level URL containing composes",
)
@click.option(
    "--name",
    help="OS name for which to check composes",
)
@click.option(
    "--version",
    help="OS version for which to check composes",
)
@click.option(
    "--description",
    help="Compose description",
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
def cli(debug, config, url, name, version, description, input, output, html):
    if debug:
        logging.basicConfig(format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")
        logger.setLevel(logging.DEBUG)
        logger.debug("Debugging mode enabled")
    else:
        logging.basicConfig(level=logging.INFO)

    if config:
        if url or name or version or description:
            logger.critical(
                "--url, --name, --version, and --description are ignored when --config is specified"
            )
            sys.exit(1)
        with open(config, "r") as f:
            conf = yaml.safe_load(f)
    else:
        if not (url and name and version):
            logger.critical(
                "Either --config OR --url, --name, and --version must be specified"
            )
            sys.exit(1)
        conf = {
            "composes": [
                {
                    "url": url,
                    "name": name,
                    "version": version,
                    "description": description,
                }
            ]
        }

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

    for compose in conf["composes"]:
        result = get_compose_result(
            compose["url"],
            compose["name"],
            compose["version"],
            compose["description"],
            today,
        )
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
