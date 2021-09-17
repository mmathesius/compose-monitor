#!/usr/bin/python3

import json
import re
import urllib.request

from bs4 import BeautifulSoup as Soup


def get_composes(composes_url, name="Fedora-ELN", version="Rawhide"):
    """
    composes_url: top level URL containing composes

    returns: ordered list of composes, from newest to oldest
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
    """"""
    print(f"Getting status for {compose = }")

    weburl = urllib.request.urlopen("{}/{}/STATUS".format(composes_url, compose))
    data = weburl.read()
    encoding = weburl.info().get_content_charset("utf-8")
    text = data.decode(encoding)
    print("Status: {}".format(text.rstrip()))

    weburl = urllib.request.urlopen(
        "{}/{}/compose/metadata/composeinfo.json".format(composes_url, compose)
    )
    data = weburl.read()
    encoding = weburl.info().get_content_charset("utf-8")
    composeattrs = json.loads(data.decode(encoding))
    # print(f"Composeinfo: {composeattrs}")
    print("Composedate: {}".format(composeattrs["payload"]["compose"]["date"]))


if __name__ == "__main__":

    url = "https://composes.stream.centos.org/production"
    print(f"For {url =}:")
    composes = get_composes(url, "CentOS-Stream", "9")
    for c in composes:
        try:
            compose_status(url, c)
        except Exception as e:
            print("Unexpected error: {}".format(e))

    url = "https://odcs.fedoraproject.org/composes/production"
    print(f"For {url =}:")
    composes = get_composes(url, "Fedora-ELN", "Rawhide")
    for c in composes:
        try:
            compose_status(url, c)
        except Exception as e:
            print("Unexpected error: {}".format(e))
