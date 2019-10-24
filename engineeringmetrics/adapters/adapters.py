#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Data Adapters
This module handles creation and authorisation of a set of data source adapters for
pulling engineering metrics.
"""
from dateutil.parser import parse
from datetime import datetime
import numpy as np
from typing import List, Dict

from configparser import ConfigParser
from jira import JIRA
import os


class JiraIssue(dict):
    """Karhoo Ticket
    Representation of tickets in Karhoo Jira.

    Attributes:
        key (unicode): Unique identifier for the ticket in its system of record
        created_at (datetime): When was the ticket created
        updated_at (datetime): When was the ticket last updated
        type (str): The kind of ticket this is: Bug, Epic, Story, etc.

    Optional Attributes:
        title (unicode): The title of the ticket
    """

    def __init__(self, issue: JIRA.issue) -> None:
        """Init a JiraIssue.

        Args:
            issue: A JIRA issue instance
        """
        # super(JiraIssue, self).__init__()
        try:
            self['ttype'] = issue.fields.issuetype.name
        except AttributeError:
            self['ttype'] = "Ticket"
        self._issue = issue

        self['id'] = issue.id
        self['key'] = issue.key
        self['url'] = issue.permalink()
        self['summary'] = issue.fields.summary
        self['labels'] = issue.fields.labels
        self['created'] = parse(issue.fields.created)
        self['updated_at'] = parse(issue.fields.updated)
        self['resolution'] = issue.fields.resolution
        self['resolutiondate'] = issue.fields.resolutiondate
        self['assignee'] = issue.fields.assignee
        self['description'] = issue.fields.description
        self['priority'] = issue.fields.priority.__str__().split(':')[0]
        self['status'] = issue.fields.status
        self['fixVersion'] = None
        if len(issue.fields.fixVersions) > 0:
            self["fixVersion"] = issue.fields.fixVersions[0]
        self['updated_at'] = None

        self._flow_log = FlowLog()
        self._flow_log.append(
            dict(
                entered_at=self['created'],
                state=str("Created")
            )
        )

        try:
            previous_item = None
            for history in issue.changelog.histories:
                for item in history.items:
                    if item.field == 'status':
                        new_log_item = dict(
                            entered_at=parse(history.created),
                            state=str(item.toString)
                        )
                        if previous_item != None:
                            previous_item['duration'] = np.busday_count(  # pylint: disable=unsupported-assignment-operation
                                previous_item['entered_at'].date(), new_log_item['entered_at'].date())  # pylint: disable=unsupported-assignment-operation, unsubscriptable-object
                        previous_item = new_log_item
                        self._flow_log.append(new_log_item)
            if previous_item != None:
                previous_item['duration'] = np.busday_count(
                    previous_item['entered_at'].date(), datetime.now().date())
        except AttributeError:
            pass

    @property
    def flow_log(self):
        """FlowLog[dict].

        A list of dicts with the following keys:
            entered_at (datetime): When the ticket entered the state
            state (unicode): The name of the state the ticket entered
            duration (int): Time spent in this state
        """
        return self._flow_log

    @property
    def cycleTime(self, resolution_status: str = None) -> int:
        """Counts the number of business days an issue took to resolve. This is
        the number of weekdays between the created data and the resolution date
        field on a ticket that is set to resolved. If no resolution date exists
        and the resolution_status paramter was passed the date a ticket entered the
        resolution status is used in place of resolution date.

        If both a resolution date found and resolution_status is set the resolution date
        is used. If neither a resolution date or resolution status are found 0 is returned.

        Args:
            resolution_status: A status to use in the case where no resolution date is set

        Returns:
            out: Number of days to resolve ticket or 0 if ticket is not resolved.
        """
        return np.busday_count(self['created'], self['resolutiondate'])


class FlowLog(list):
    """List subclass enforcing dictionaries with specific keys are added to it."""

    def append(self, value):
        """Add items to the list.

        Args:
            value (dict): Must contain an entered_at and state key.

        Returns:
            None

        Raises:
            TypeError: Flow log items must have a 'entered_at' datetime and a 'state' string.
        """
        try:
            ('entered_at', 'state') in value.keys()
        except AttributeError:
            raise TypeError(
                "Flow log items must have a 'entered_at' datetime and a 'state' string. Got: {value}".format(value=value))

        entered_at = value['entered_at']
        try:
            datetime.now(entered_at.tzinfo) - entered_at
        except (AttributeError, TypeError) as e:
            msgvars = dict(
                val_type=type(entered_at),
                val=entered_at,
                exc=str(e)
            )
            raise TypeError(
                "Flow log items must have a entered_at datetime. Got: {val_type} / {val}, \n Exception: {exc}".format(**msgvars))

        value[u'state'] = str(value['state'])
        super(FlowLog, self).append(value)
        self.sort(key=lambda l: l['entered_at'])


class JQLResult():

    def __init__(self, query: str, label: str = 'JQL', issues: List[JiraIssue] = []) -> None:
        """Init a JQLResult

        Args:
            query: The JQL query to perform against the Jira data.
            label (optional): A string label to store the quert result internally. If not set the query
                    reult is stored undert the key 'JQL' and overwrites any previous query results.
        """
        self._query = query
        self._label = label
        self._issues = issues

    @property
    def query(self) -> str:
        """query

        The query that was run for this result set.
        """
        return self._query

    @property
    def label(self) -> str:
        """label

        A label for this query.
        """
        return self._label

    @property
    def issues(self) -> List[JiraIssue]:
        """Issues

        A list of wrapped jira issues.
        """
        return self._issues


class JiraProject(JQLResult):
    """Karhoo Ticket
    Representation of projects in Karhoo Jira.

    """

    def __init__(self, project: JIRA.project, query_string: str = '') -> None:
        """Init a JiraProject

        Args:
            project: A JIRA project instance
        """
        super().__init__(query_string, project.name)
        self._key = project.key
        self._name = project.name

    @property
    def key(self) -> str:
        """Key

        The project name as it is in Jira.
        """
        return self._key

    @property
    def name(self) -> str:
        """Name

        The project name as it is in Jira.
        """
        return self._name


class Jira:
    """An Engineering Metrics wrapper for data we can harvest from Jira.

    Attributes:
        jiraclient (JIRA): The instance of Jira's python client used to pull the data from metrics.
        projects Dict[str, JiraProject]: A dictionary of Karhoo projects by project key.
    """

    def __init__(self, jiraclient: JIRA) -> None:
        self._client = jiraclient
        self._datastore = {
            "issues": {},
            "projects": {}
        }

    def _getJiraIssuesForProjects(self, project_ids: List[str]) -> Dict[str, JiraProject]:

        issues_by_project = {}
        for pid in project_ids:
            print(f'Request data for project id {pid}')
            pdata = self._client.project(pid)
            print(f'Data received for project id {pid}')

            query_string = 'project = "{}" ORDER BY priority DESC'.format(pid)
            proj = JiraProject(pdata, query_string)
            print(f'Request issues for project id {pid}')
            issues = self._client.search_issues(
                query_string,
                maxResults=10,
                expand='changelog'
            )
            print(f'Issues received for project id {pid}')
            for issue in issues:
                kt = JiraIssue(issue)
                proj.issues.append(kt)

            if len(proj.issues):
                issues_by_project[pid] = proj

        return issues_by_project

    def populate_projects(self, projectids: List[str]) -> Dict[str, Dict[str, object]]:
        """Populate the Karhoo Jira instance with data from the Jira app.

        Given a list of ids this method will build a dictionary containing issues from
        each project in the list. As well as retuning the data to the callee, this method
        stores the results internally to facilitate the use of a range of helper methods
        to analyse the data.

        Args:
            projectids: A list of project ids for which you want to pull issues.

        Returns:
            A dictionary of JiraProjects, Each key will be the project id which maps to
            a JiraProjects of the form
            {
                "name" (str): Project name
                "key"  (str): Project Key
                "issues" List[JiraIssues]: A list of wrapped Jira issues
            }

        """
        projects = self._getJiraIssuesForProjects(projectids)
        self._datastore['projects'] = {
            **self._datastore['projects'], **projects}
        return projects

    def populate_from_jql(self, query: str = None, label: str = "JQL") -> Dict[str, object]:
        """Populate the Karhoo Jira instance with data from the Jira app accorging to a JQL
        string.

        Given a JQL string this method will build a dictionary containing issues returned
        by executing the query. As weel as retuning the data to the callee, this method
        stores the results internally to facilitate the use of a range of helper methods
        to analyse the data.

        Args:
            query: The JQL query to perform against the Jira data.
            label (optional): A string label to store the quert result internally. If not set the query
                    reult is stored undert the key 'JQL' and overwrites any previous query results.

        Returns:
            a dictionary of the form
            {
                "name" (str): Set to the query string
                "key"  (str): Key used to store the result (set to label if provided or 'JQL' otherwise)
                "issues" List[JiraIssues]: A list of wrapped Jira issues
            }

        """
        if query == None:
            raise ValueError("query string is required to get issues")

        result = self._client.search_issues(
            query, maxResults=False, expand='changelog')
        issues = list(map(lambda i: JiraIssue(i), result))
        query_result = JQLResult(query, label, issues)
        self._datastore[query_result.label] = query_result
        return query_result

    def get_query_result(self, label: str = 'JQL') -> Dict[str, object]:
        """Get a cached JQL query result dictionary

        Args:
            label (optional): The label supplied with the original query

         Returns:
            a dictionary of the form
            {
                "name" (str): Set to the query string
                "key"  (str): Key used to store the result (set to label if provided or 'JQL' otherwise)
                "issues" List[JiraIssues]: A list of wrapped Jira issues
            }
        """
        return self._datastore[label]

    def get_project(self, pid: str) -> JiraProject:
        """Get a cached Kerhoo Project instance for a given pid

        Args: 
            pid: The project key assigned by Jira.

        Returns: A Karhoo Project instance populated with its issues.

        """
        try:
            project = self._datastore['projects'][pid]
            return project
        except KeyError:
            return KeyError(f'No project with key {pid} in the cache. Have you called Jira.populate_projects(["{pid}"])?')

    @property
    def jiraclient(self) -> JIRA:
        """JiraClient

        The instance of Jira's python client wrapped by this adapter.
        """
        return self._client

    @property
    def projects(self) -> Dict[str, JiraProject]:
        """Projects

        A dictionary of Karhoo Project instances by project key e.g. INT
        """
        return self._datastore['projects']


def init_jira_adapter(jira_oauth_config_path: str = None, jira_access_token: str = None) -> Jira:
    if jira_oauth_config_path != None:
        path_to_config = os.path.join(jira_oauth_config_path,
                                      '.oauthconfig/.oauth_jira_config')
        print()

        print(
            f'Reading OAuth from {path_to_config}')

        config = ConfigParser()
        config.read(path_to_config)
        jira_url = config.get("server_info", "jira_base_url")
        oauth_token = config.get("oauth_token_config", "oauth_token")
        oauth_token_secret = config.get(
            "oauth_token_config", "oauth_token_secret")
        consumer_key = config.get("oauth_token_config", "consumer_key")

        rsa_private_key = None
        # Load RSA Private Key file.
        with open(os.path.join(jira_oauth_config_path, '.oauthconfig/oauth.pem'), 'r') as key_cert_file:
            rsa_private_key = key_cert_file.read()

        if jira_url[-1] == '/':
            jira_url = jira_url[0:-1]

        oauth_dict = {
            'access_token': oauth_token,
            'access_token_secret': oauth_token_secret,
            'consumer_key': consumer_key,
            'key_cert': rsa_private_key
        }

        return Jira(JIRA(oauth=oauth_dict, server=jira_url))
