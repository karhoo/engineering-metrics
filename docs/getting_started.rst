Getting Started
===============

Getting your application tokens
+++++++++++++++++++++++++++++++
Jira Cloud
__________

Jira Cloud provides access to the api through a token. Get your token from `Atlassian <https://id.atlassian.com/manage/api-tokens>`_.

Jira Server
___________

For Jira server we require oAuth. To set this up follow this `guide <https://github.com/karhoo/engineering_metrics/tree/master/token_generator>`_.

Create your first report
________________________


There is an `example <https://github.com/karhoo/engineering_metrics/tree/master/examples>`_ as a Jupyter notebook. This won't run in github as it needs authentication, so until I get it hosted you can run it locally using `your jupyter setup <https://jupyter.readthedocs.io/en/latest/install.html>`_.

Otherwise a quick start (after setting up you oAuth credentials) is
given here.::

    from engineeringmetrics import EngineeringMetrics

    # Assuming we are on Jira Cloud
    config_dict = {
        'jira_username': '<YourJira@CloudUsername>',
        'jira_api_token': 'YourbP0APIkavuKeyQ72C4',
        'jira_server_url': 'https://karhoo.atlassian.net'
    }

    EM = EngineeringMetrics(config_dict)
    projects_data = EM.jirametrics.populate_projects(['INT'],  max_results=100)

Now you can start diving in to your Jira issues. Lets produce a markdown
report of some know issues from one of our projects.

First we need a couple of helper functions that just build strings out of
data from our jira query::

    def pPriority(priority: str) -> str:
        """Parse status in to P1 - P4 and add some emotion!"""

        s = ''
        if priority == 'Blocker':
            s += "P1 🚨😫😭"
        elif priority == 'Highest':
            s += "P2 😭😭"
        elif priority == 'High':
            s += "P3 😟"
        elif priority == "Normal":
            s += "P4 🤔"
        return s


    def createMarkdownReport(project: :py:class:`engineeringmetrics.adapters.JiraProject`) -> str:
        """Create a string in markdown format from data from our jira query"""

        s = "# Known Issues Report\n"
        s += "Generated automatically from JIRA\n"
        s += '\n'
        s += "## {} Known Issues\n".format(project.name)
        for issue in project.issues:
            url = issue['url']
            s += "#### {} ([{}]({})) {}\n".format(issue.['key'],
                                                issue.['summary'], url, pPriority(issue['priority']))
            # s += pPriority(issue['priority'])
            s += "* JIRA: [{}]({})\n".format(url, url)
            s += "* Status: {}\n".format(issue['status'])
            if issue['fixVersion']:
                s += "* Fix: This was fixed in version {}\n".format(
                    issue['fixVersion'])
            s += '\n'
        return s

Now we can pass in our JiraProject instance and push our markdown string
to a report file. ::

    import os

    SCRIPT_PATH = os.path.dirname(os.path.abspath(__file__))
    MARKDOWN_FILE = f'{SCRIPT_PATH}/report.md'

    md = createMarkdownReport(project_list['INT'])
    with open(MARKDOWN_FILE, 'w', encoding='utf-8') as f:
        f.write(md)
