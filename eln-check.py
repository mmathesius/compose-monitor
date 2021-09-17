#!/usr/bin/python3

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

    html = urllib.request.urlopen(composes_url).read()
    soup = Soup(html, "html.parser")

    comp_links = soup.find_all("a", href=compose_re)

    comps = []
    for link in comp_links:
        match = re.search(compose_re, link["href"])
        group = match.group()
        comps.append(group)

    return sorted(comps, key=str.lower, reverse=True)


if __name__ == "__main__":

    url = "https://odcs.fedoraproject.org/composes/production"
    composes = get_composes(url, "Fedora-ELN", "Rawhide")
    print(f"{composes = }")

    url = "https://composes.stream.centos.org/production"
    composes = get_composes(url, "CentOS-Stream", "9")
    print(f"{composes = }")
