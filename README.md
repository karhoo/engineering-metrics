# Karhoo Engineering Metrics
A python lib to pull out some engineering metrics from various data sources such as issue tracking software and event logs.

## Getting Started

There are two ways to install this module for use in your data investigations. Clone the repo and install it locally (which gives you access to the docs too) or install it via pip from github.

```sh
# Local install (recommended so you can build the docs locally)
# Over ssh
git clone git@github.com:karhoo/engineering_metrics.git
cd engineering_metrics/
python setup.py install

# pip install from github
pip install git+ssh://git@github.com/karhoo/engineering_metrics.git#egg=engineeringmetrics
```

### Docs

Documentation site is on [readthedocs](https://engineering-metrics.readthedocs.io/en/latest/). To view them locally clone the repo, build the docs and view in your favorite browser (or one you don't like but have installed).

```sh
# Requires python 3.6. Get you virtual env out.
pip install -r requirements.docs.txt
cd docs/
make html
```

The docs are written to the sub directory `_build/html` and can be viewied from the `index.html` page.

```sh
# e.g. On mac
open  "_build/html/index.html"
```

### Jira Cloud api token

Auth is a much easier game with Jira cloud. You simply need an api token. Get one [here](https://id.atlassian.com/manage/api-tokens) and then use it to initiate the Engineering Metrics lib.

```python
from engineeringmetrics import EngineeringMetrics

config_dict = {
    'jira_username': '<YourJira@CloudUsername>',
    'jira_api_token': 'YourbP0APIkavuKeyQ72C4',
    'jira_server_url': 'https://karhoo.atlassian.net'
}
kem = EngineeringMetrics(config_dict)
```

### oAuth for Jira Server
Until we hit the cloud you will need to generate some access tokens to use this library against the Jira Server instance we have. This can be done using the script found in the `token_generator` directory. Follow the [README](./token_generator/README.md) down the rabbit hole.
