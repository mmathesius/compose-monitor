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


def find_compose_result(compose, results):
    """
    Find result in `results` that matches `url`, `name`, and `version` from `compose`

    :param compose: dict containing compose-specific configuration
    :param results: dict containing all compose results
    :return: matching compose entry from `results`, else None
    """
    if results is None:
        return None

    for comp in results["composes"]:
        if (
            comp["url"] == compose["url"]
            and comp["name"] == compose["name"]
            and comp["version"] == compose["version"]
        ):
            return comp

    return None


def get_compose_config_prop(prop, conf, compose):
    """
    Get a compose configuration property, also checking the defaults.

    :param prop: property name to get
    :param conf: dict containing configuration
    :param compose: dict containing compose-specific configuration
    """
    val = compose.get(prop)
    if val is None:
        try:
            val = conf["defaults"][prop]
        except:
            pass
    return val


def send_alert(result, alert_days, email_sender, email_to, extra=None):
    logger.info(
        "Sending compose {} alert to {} from {}".format(
            result["description"], email_to, email_sender
        )
    )

    fmt = {}
    fmt["description"] = result["description"]
    fmt["alert_days"] = alert_days

    for what in ["latest_attempted", "latest_finished", "latest_incomplete"]:
        for prop in ["age", "date", "id", "url"]:
            fmt[what + "_" + prop] = result[what].get(prop, "unknown-" + prop)

    if extra:
        fmt["extra"] = "\nAdditional details:\n{}\n".format(extra)
    else:
        fmt["extra"] = ""

    subject = "[COMPOSE FAILURE] {description} has not finished for {latest_finished_age} days".format(
        **fmt
    )
    message = """Greetings.

{description} has not finished successfully since {latest_finished_date} ({latest_finished_age} days ago)."

You are receiving this message because the configured alert threshold of {alert_days} days has been reached.

Latest finished compose was {latest_finished_id} on {latest_finished_date} ({latest_finished_age} days ago).
    Link: {latest_finished_url}

Latest incomplete compose was {latest_incomplete_id} on {latest_incomplete_date} ({latest_incomplete_age} days ago).
    Link: {latest_incomplete_url}

Latest attempted compose was {latest_attempted_id} on {latest_attempted_date} ({latest_attempted_age} days ago).
    Link: {latest_attempted_url}
{extra}""".format(
        **fmt
    )

    logger.info("Subject: {}".format(subject))
    logger.info("Body: {}".format(message))


def alerts(conf, results, old_results):
    """
    Send alerts as per configuration

    :param conf: dictionary containing configuration
    :param results: status results for configured composes
    :param old_results: status results for configured composes from previous run
    """
    logger.info("Sending alerts")

    today = results["date"]

    for compose in conf["composes"]:
        logger.info("Processing alert for {} compose".format(compose["description"]))
        email_to = get_compose_config_prop("email_to", conf, compose)
        logger.info("E-mail recipients: {}".format(email_to))
        if not email_to:
            logger.info("No e-mail recipients; skipping")
            continue

        logger.debug("Looking for compose: {}".format(compose))
        result = find_compose_result(compose, results)
        logger.debug("Current result finding: {}".format(result))
        old_result = find_compose_result(compose, old_results)
        logger.debug("Old result finding: {}".format(old_result))

        alert_days = get_compose_config_prop("alert_days", conf, compose)

        if result["latest_finished"] and result["latest_finished"]["age"] < alert_days:
            logger.info(
                "Alert threshold of {} days has not been reached; skipping".format(
                    alert_days
                )
            )
            continue

        if old_result and "alert_date" in old_result:
            alert_date = old_result["alert_date"]
        else:
            alert_date = "00000000"

        if alert_date < today:
            email_sender = get_compose_config_prop("email_sender", conf, compose)
            extra = get_compose_config_prop("extra", conf, compose)
            send_alert(result, alert_days, email_sender, email_to, extra)
        else:
            logger.info("Alert already sent for today")

        result["alert_date"] = today


def render(results, tmpl_path="templates", output_path="output", fmt="all"):
    os.makedirs(output_path, exist_ok=True)

    j2_env = jinja2.Environment(loader=jinja2.FileSystemLoader(tmpl_path))
    templates = j2_env.list_templates(extensions="j2")
    logging.debug("Templates to render found in {}: {}".format(tmpl_path, templates))
    if fmt != "all":
        fmtlist = fmt.split(",")
        templates = [name for name in templates if name.split(".")[-2] in fmtlist]
    for tmpl_name in templates:
        tmpl = j2_env.get_template(tmpl_name)
        out = os.path.join(
            output_path,
            tmpl_name[:-3],
        )
        tmpl.stream(results=results).dump(out)
        logger.info("{} results written to {}".format(tmpl_name, out))


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
def cli(debug, config, url, name, version, description, input, output):
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
    results["date"] = today.strftime("%Y%m%d")
    results["now"] = now.strftime("%Y-%m-%d %H:%M:%S")

    logger.debug("Today is {}".format(results["date"]))
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

    alerts(conf, results, old_results)

    if output:
        with open(output, "w") as f:
            yaml.safe_dump(results, f)
        logger.info("YAML results saved to {}".format(output))

    render(results, tmpl_path=os.path.join(SCRIPTPATH, "templates"))


if __name__ == "__main__":
    cli()
