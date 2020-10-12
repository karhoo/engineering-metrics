#!/usr/bin/python
# -*- coding: utf-8 -*-
"""This module handles creation and authorisation of a set of data source adapters for
pulling engineering metrics.
"""
from dateutil.parser import parse
from datetime import datetime, timedelta
import numpy as np
from typing import List, Dict

from configparser import ConfigParser
from jira import JIRA, client
import json
import os


def busday_duration(date_a: datetime, date_b: datetime = None, interval="hours") -> int:
    """
    Returns a duration as specified by variable interval. Only includes business days.
    Functions, except totalDuration, returns[quotient, remainder]

    Args:
        date_a:
            First date
        date_a (Optional):
            Second date

    Returns:
        The duration between the two dates in the interval indicated (or hours if none is given)

    """
    if date_b == None:
        date_b = datetime.now(date_a.tzinfo)
    full_duration = date_b - date_a
    # pylint: disable=no-member
    bus_days = np.busday_count(
        date_a.date(), date_b.date()).item()
    duration = full_duration

    if full_duration.days == 2 and bus_days == 1:
        duration = full_duration - timedelta(days=(2))
    elif full_duration.days > bus_days:
        duration = full_duration - \
            timedelta(days=(full_duration.days - bus_days))

    duration_in_s = duration.total_seconds()

    def years():
        return divmod(duration_in_s, 31556926)  # Seconds in a year=31556926.

    def days(seconds=None):
        # Seconds in a day = 86400
        return divmod(seconds if seconds != None else duration_in_s, 86400)

    def hours(seconds=None):
        # Seconds in an hour = 3600
        return divmod(seconds if seconds != None else duration_in_s, 3600)

    def minutes(seconds=None):
        # Seconds in a minute = 60
        return divmod(seconds if seconds != None else duration_in_s, 60)

    def seconds(seconds=None):
        if seconds != None:
            return divmod(seconds, 1)
        return duration_in_s

    def totalDuration():
        y = years()
        d = days(y[1])  # Use remainder to calculate next variable
        h = hours(d[1])
        m = minutes(h[1])
        s = seconds(m[1])

        return "Time between dates: {} years, {} days, {} hours, {} minutes and {} seconds".format(int(y[0]), int(d[0]), int(h[0]), int(m[0]), int(s[0]))

    return {
        'years': int(years()[0]),
        'days': int(days()[0]),
        'hours': int(hours()[0]),
        'minutes': int(minutes()[0]),
        'seconds': int(seconds()),
        'default': totalDuration()
    }[interval]


class FlowLog(list):
    """List subclass enforcing dictionaries with specific keys are added to it.

    A flow log is attached to each :py:class:`JiraIssue` in order to surface an issues journey
    through the workflow. Each entry in a flow log is a dictionary with the following keys:

        ``"entered_at"``
            When the issue entered the state (datetime)
        ``"state"``
            The name of the state the issue entered (string)
        ``"duration"``
            Time spent in this state (int)

    This should faciliate reporting on cycle time and should help to surface bottlenecks, by allowing
    issues to be graphed with regard to the time they spend in each ``"state"`` of a workflow.

    """

    def append(self, value: dict) -> None:
        """Add items to the list.

        Args:
            value (dict): Must contain an ``"entered_at"`` and ``"state key"``.

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

    def as_dict(self) -> Dict[str, str]:
        log_as_dic = {}
        for item in self:
            status = item['state']
            log_as_dic[status] = log_as_dic.get(
                status, 0) + item.get('duration', 0)
        return log_as_dic


class JiraIssue(dict):
    """Representation of issues from Jira.

    Attributes:
        assignee (Dict):
            Dict of properties parsed out of the JSON response from the server

            ``"accountId"``
            ``"accountType"``
            ``"active"``
            ``"avatarUrls"``
            ``"displayName"``
            ``"emailAddress"``
            ``"key"``
            ``"name"``
            ``"self"``
            ``"timeZone"``

            where ``"self"`` is the URL to the user in Jira Cloud.
        comments (List):
            A list of comments. Each comment of the list is a `dict` with the following keys:

            ``"author"``
            ``"body"``
            ``"created"``
            ``"id"``
            ``"self"``
            ``"updateAuthor"``
            ``"updated"``

            where ``"self"`` is the URL to the comment in Jira Cloud.
        created (date):
            Date issue was created.
        cycle_time (int):
            This is a calculated attribute based on the date work stared on the issue. It 
            relies on the issue to have been resolved and looks to calculate the number
            of hours between work starting and completion of an issue. See ``calculate_cycle_time``
            for more details.
        description (string):
            Details of the issue.
        epic_links (string):
            Epic this issue is in.
        fix_version (string):
            The latest fix version associated with this issue.
        flow_log (:py:class:`FlowLog`):
            A list of status changes for the issue. See :py:class:`FlowLog` for more details.
        id (string):
            The Jira Cloud id for this issue.
        issue_links (List):
            A list of issue keys that are linked to this issue.
        key (string):
            The Jira Cloud key for this issue.
        labels (List):
            A list of lables added to the issue. Very useful :)
        lead_time (int):
            This is a calculated attribute based on the created date of the issue. It 
            relies on the issue to have been resolved and looks to calculate the number
            of hours between creation and completion of an issue. See ``calculate_lead_time``
            for more details.
        parent (str):
            If the issue is a sub-types this attribute records the parent issue id.
        project (string):
            The Jira Cloud key for the project this issue is associated to.
        project_name (string):
            The name of the project this issue is associated to.
        priority (string):
            The name of the priority given to this issue.
        resolution (string):
            Name description of the resolution of the issue (only if issue is resolved).
        resolution_date (string):
            Date issue was resolved.
        status (Dict):
            Current status of the issue. Contains the keys:

            ``"description"``
            ``"iconUrl"``
            ``"id"``
            ``"name"``
            ``"self"``
            ``"statusCategory"``

             where ``"name"`` is probably the key of most interest. **NOTE: Here the url stored in the**
             ``"self"`` **key is to the universal description of this staus and not just in the
             context of our issue.**
        summary (string):
            The sumary line for the issues. Think of it as a short description.
        url (string):
            URL back to the issue on Jira Cloud.
        updated_at (string):
            The date of the last update to this issue.

    A JiraIssue extends the python `dict` class and we add a set of key/value pairs to the JiraIssue
    that may be of interest to the user whilst building reports. For example, the dictionary values allow 
    for a JiraIssues to be used as a row in a `pandas dataframe <https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.DataFrame.from_dict.html#pandas-dataframe-from-dict>`_
    with each key mapping to a column.

    For each attribute (with underscore style naming) you will find a corresponding key entry
    (in camel case) in the dictionary with the exception of ``assignee`` and ``comments``. In addition 
    the following keys are added without a corresponding class attribute (but can be generated from an
    attribute if so desired):

        ``"assigneeName"``
            The name of hte person assigned to this issue (or None)
        ``"assigneeEmail"``
            The email of the assigned persone (or None)
        ``"lastComment"``
            If there are any comments on this issue (accessed on the comments attribute) this will be the last of them
        ``"lastCommentDate"``
            The date the `lastComment` was created
    """

    def __init__(self, issue: JIRA.issue) -> None:
        """Init a JiraIssue.

        Args:
            issue: A JIRA issue instance
        """
        try:
            self['ttype'] = issue.fields.issuetype.name
        except AttributeError:
            self['ttype'] = "Ticket"
        self._issue = issue

        if issue.fields.assignee:
            self.assignee = issue.fields.assignee.raw
            self['assigneeName'] = self.assignee.get('displayName')
            self['assigneeEmail'] = self.assignee.get('emailAddress')

        try:
            self.comments = list(
                map(lambda c: c.raw, issue.fields.comment.comments))
            if len(self.comments) > 0:
                self['lastComment'] = self.comments[0]['body']
                self['lastCommentDate'] = self.comments[0]['created']
            self['comments'] = json.dumps([c.get('body') for c in self.comments])
        except:
            pass
        
        self.created = parse(issue.fields.created)
        self['created'] = self.created

        self.description = issue.fields.description
        self['description'] = self.description

        self.fix_version = None
        if len(issue.fields.fixVersions) > 0:
            self.fix_version = issue.fields.fixVersions[0]
        self['fixVersion'] = self.fix_version

        self.id = issue.id
        self['id'] = self.id

        self.key = issue.key
        self['key'] = self.key

        self.project = issue.fields.project.key
        self['project'] = self.project

        self.project_name = issue.fields.project.name
        self['projectName'] = self.project_name

        self.labels = issue.fields.labels
        self['labels'] = self.labels

        self.priority = issue.fields.priority.name
        self['priority'] = self.priority

        self.resolution = issue.fields.resolution
        self['resolution'] = self.resolution
        self.resolution_date = parse(
            issue.fields.resolutiondate) if issue.fields.resolutiondate else ''
        self['resolutionDate'] = self.resolution_date

        self.status = issue.fields.status.raw
        self['status'] = self.status['name']

        self.summary = issue.fields.summary
        self['summary'] = self.summary

        self.url = issue.permalink()
        self['url'] = self.url

        self.updated_at = parse(issue.fields.updated)
        self['updatedAt'] = self.updated_at

        # The following allows you to debug individual fields per
        # https://stackoverflow.com/questions/30615846/python-and-jira-get-fields-from-specific-issue
        #for field_name in issue.raw['fields']:
        #   print('-------')
        #   print(f"Field: '{field_name}', Value: {issue.raw['fields'][field_name]}")
        #print(type(issue.raw))
        #print(dir(issue.raw))
        #print(issue.raw.keys())
        #print("============================================================")
        # 10001 is old JIRA.  New JIRA has a whole new parent thing going on
        if getattr(issue.fields, 'parent', None):
            self['epiclink'] = issue.fields.parent.key
            self['epicName'] = issue.fields.parent.fields.summary
        else:
            self['epiclink'] = issue.fields.customfield_10001

        # Story points: https://community.atlassian.com/t5/Answers-Developer-Questions/Story-Points-CustomField-Table/qaq-p/575830
        # Doesn't work.  Can't get see this custom field in issue :-/
        #self['storyPoints'] = issue.fields.customfield_10006

        self.issue_links = []
        for link in issue.fields.issuelinks:
            if getattr(link, 'inwardIssue', None):
                self.issue_links.append(link.inwardIssue.key)
        self['issueLinks'] = self.issue_links

        parent = getattr(issue.fields, 'parent', None)
        self.parent = parent.key if parent else parent

        self.flow_log = FlowLog()
        self.flow_log.append(
            dict(
                entered_at=self['created'],
                state=str("Created")
            )
        )
        try:
            previous_item = None
            for history in reversed(issue.changelog.histories):
                for item in history.items:
                    if item.field == 'status':
                        new_log_item = dict(
                            entered_at=parse(history.created),
                            state=str(item.toString)
                        )
                        if previous_item != None:
                            previous_item['duration'] = busday_duration(  # pylint: disable=unsupported-assignment-operation
                                previous_item['entered_at'], new_log_item['entered_at'])  # pylint: disable=unsupported-assignment-operation, unsubscriptable-object
                        previous_item = new_log_item
                        self.flow_log.append(new_log_item)
            if previous_item != None:
                previous_item['duration'] = busday_duration(
                    previous_item['entered_at'], datetime.now(previous_item['entered_at'].tzinfo))
        except AttributeError:
            pass

        self['leadTime'] = None
        self.calculate_lead_time()
        self.lead_time = self['leadTime']

        # We do this after the flow log is built as cycleTime uses data from that log.
        self['cycleTime'] = None
        self.calculate_cycle_time()
        self.cycle_time = self['cycleTime']

    def calculate_lead_time(self, resolution_status: str = 'Done', override: bool = False) -> int:
        """Counts the number of business days an issue took to resolve. This is
        the number of weekdays between the created date and the resolution date
        field on a issue that is set to resolved. If no resolution date exists
        and the resolution_status paramater was passed the date a issue entered the
        resolution status is used in place of resolution date.

        If both a resolution date found and resolution_status is set the resolution date
        is used. If neither a resolution date or resolution status are found -1 is returned.

        Args:
            resolution_status: A status to use in the case where no resolution date is set

        Returns:
            Number of days to resolve issue or -1 if issue is not resolved.
        """
        self['leadTime'] = -1

        if self.resolution_date and not override:
            self['leadTime'] = busday_duration(
                self.created, self.resolution_date)
        else:
            resolution_date = None
            for log in self.flow_log:
                if log['state'] == resolution_status:
                    resolution_date = log['entered_at']
            if resolution_date != None:
                self['leadTime'] = busday_duration(
                    self.created, resolution_date)

        return self['leadTime']

    def calculate_cycle_time(self, begin_status: str = 'In Progress', resolution_status: str = 'Done', override: bool = False) -> int:
        """Calculates the number of business days an issue took to resolve once work had begun. As a
        issue is often created before work is stared this method uses the date an issue entered a
        particular state to indicate the start of work. IT assumes a state called "In Progress" if nothing
        is given.

        Cycle time is the number of weekdays between the start of work on the issue and the resolution
        date field on a issue that is set to resolved. If no resolution date exists and the resolution_status
        paramater was passed the date a issue entered the resolution status is used in place of resolution date.

        If both a resolution date found and resolution_status is set the resolution date
        is used. If neither a resolution date or resolution status are found -1 is returned.

        Args:
            begin_status: A status to use to understand when the work was started on this issue
            resolution_status: A status to use in the case where no resolution date is set

        Returns:
            Number of days to resolve issue or -1 if issue is not resolved.
        """
        self['cycleTime'] = -1

        start_date = None
        for log in self.flow_log:
            if log['state'] == begin_status:
                start_date = log['entered_at']
        if start_date == None:
            start_date = self.created

        resolution_date = None
        if self.resolution_date:
            resolution_date = self.resolution_date
        elif override:
            for log in self.flow_log:
                if log['state'] == resolution_status:
                    resolution_date = log['entered_at']

        if resolution_date != None:
            self['cycleTime'] = busday_duration(start_date, resolution_date)

        return self['cycleTime']

    __PROTECTED_FIELDS__ = ['key', 'ttype']

    def filtered_copy(self, fields_filter: List[str]) -> 'JiraIssue':
        """Return a copy of this JiraIssue instance with only the set of fields defined in the fields_filter list.

        id and ttype are protected fields and cannot be removed by this method.

        Args:
            fields_filter:
                List of field names to include in the filtered copy. Available fields are
                ``"assignee"``, ``"created"``, ``"cycleTime"``, ``"description"``, ``"fixVersion"``, ``"fixVersion"``, ``"id"``, ``"key"``,
                ``"labels"``, ``"leadTime"``, ``"parent"``, ``"priority"``, ``"resolution"``, ``"resolutiondate"``, ``"status"``, ``"summary"``, ``"ttype"``,
                ``"url"``, ``"updated_at"``

        Returns:
            JiraIssue: A filtered copy of this issue.
        """

        filtered = JiraIssue(self._issue)
        if type(fields_filter) is list:
            fields_filter = set().union(self.__PROTECTED_FIELDS__, fields_filter)
            to_delete = set(filtered.keys()).difference(fields_filter)
            for d in to_delete:
                del filtered[d]

        if 'leadTime' in fields_filter:
            filtered['leadTime'] = self.get(
                'leadTime', self.calculate_lead_time())
        if 'cycleTime' in fields_filter:
            filtered['cycleTime'] = self.get(
                'cycleTime', self.calculate_cycle_time())
        # We have to copy parent from a property into the map if it is a requested field
        if 'parent' in fields_filter:
            filtered['parent'] = filtered.parent
        return filtered


class JQLResult(list):
    """This class wraps the results of a JQL query in order to provide some convenience methods.

    Args:
        query: The JQL query that produces the result set.
        label (optional): A string label used to cache the query result. If not set the default key
            `JQL` is used and the result overwrites any previous query results.
        issues: A list of :py:class:`JiraIssue` instances.

    """

    def __init__(self, query: str, label: str = 'JQL', issues: List[JIRA.issue] = []) -> None:
        """Init a JQLResult

        Args:
            query: The JQL query that produces the result set.
            label (optional): A string label used to cache the query result. If not set the default key
                `JQL` is used and the result overwrites any previous query results.
            issues: A list of :py:class:`JiraIssue` instances.
        """
        if type(issues) is client.ResultList:
            self.extend(list(map(lambda i: JiraIssue(i), issues)))
        else:
            self.extend(issues)
        self._query = query
        self._label = label

    @property
    def query(self) -> str:
        """
        str: `query`
            The query that was run for this result set.
        """
        return self._query

    @property
    def label(self) -> str:
        """
        str: `label`
            A label for this query.
        """
        return self._label

    @property
    def issues(self) -> List[JiraIssue]:
        """
        List[:py:class:`JiraIssue`]: `issues`
            A list of :py:class:`JiraIssue` instances.
        """
        return self

    @property
    def resolved_issues(self) -> List[JiraIssue]:
        """
        List[:py:class:`JiraIssue`]: `issues`
            A list of just the issues that are understood to be resolved.

            Currently this is implemented by filtering a list of issues to only contain
            those with a lead time greater that -1.
        """
        return list(filter(lambda d: d.resolution or d.get('leadTime', -1) > -1, self))

    def calculate_lead_times(self, *args, **kwargs) -> None:
        """Calculate the lead times for all issues in this JQLResult instance.

        This method allows us to fix some issues that might be missing resolution data.
        We can pass an issue status that can be used to infer a resolution date if this is
        missing from an issue we intend as resloved.

        The date an issue entered the resolution status is only used if the resolution date is
        not set on an given issue.

        Args:
            resolution_status (str):
                The issue status that indicates the issue was resolved
        """
        for issue in self:
            issue.calculate_lead_time(*args, **kwargs)

    def calculate_cycle_times(self, override: bool = True, *args, **kwargs) -> None:
        """Calculate the cycle times for all issues in this JQLResult instance.

        This method allows us to pass issue statuses to mark begining and end of work when
        this data is not clear from the issue data retrieved in the query,

        Args:
            begin_status (str):
                The issue status that indicate work has started on this issue
            resolution_status (str):
                The issue status that indicates the issue was resolved
        """
        for issue in self:
            issue.calculate_cycle_time(override=override, *args, **kwargs)

    def expand_issue_flow_logs(self, statuses: List[str] = None):
        """Add all flow log statuses as properties on the items with the duration of that status as the value.
        This method alters the issues set of the current JQLResult in place. To undo would require using the filter
        method to select just the properties of interest.

        This is useful if you wish to plot graphs around how long issues where in each status during work intervals.

        Examples:
            To expand the flowlogs.

                .. code-block:: python

                    query_result = jm.populate_from_jql(
                            'project = "INT" AND issuetype in ("Sub-task", "Story")')
                    query_result.expand_issue_flow_logs()
        """
        for issue in self:
            status_dict = issue.flow_log.as_dict()
            if type(statuses) is list:
                to_delete = set(status_dict.keys()).difference(statuses)
                for d in to_delete:
                    del status_dict[d]
            issue.update(status_dict)

    def filter(self, issue_type_filter: List[str] = None, fields_filter: List[str] = None) -> 'JQLResult':
        """Filter the issues in this JQLResult instance.

        This method can be used to either filter out some issues you are interested in, select just
        the fields you want to use (for example to produce a pandas dataframe) or do a combination of
        both.

        Args:
            fields_filter:
                A list of fields to return on each issue. Available fields are
                ``"assignee"``, ``"created"``, ``"cycleTime"``, ``"description"``, ``"fixVersion"``, ``"fixVersion"``, ``"id"``, ``"key"``,
                ``"labels"``, ``"leadTime"``, ``"parent"``, ``"priority"``, ``"resolution"``, ``"resolutiondate"``, ``"status"``, ``"summary"``, ``"ttype"``,
                ``"url"``, ``"updated_at"``

            issue_type_filter:
                A list of issue types to return

        Returns:
            JQLResult: An new JQLResult instance with a shallow copy of the filtered issues.

        Examples:
            To filter a previous query set.

                .. code-block:: python

                    query_result = jm.populate_from_jql(
                            'project = "INT" AND issuetype in ("Sub-task", "Story")')
                    filtered = query_result.filter(['Sub-task'])
        """

        # Make a copy of the issues from this query to not return references to the exitsing ones.
        filtered_issues = list(map(lambda i: JiraIssue(i._issue), self))
        filtered_label = self.label + '_filtered'

        if type(issue_type_filter) is list:
            filtered_issues = list(
                filter(lambda fi: fi['ttype'] in issue_type_filter, filtered_issues))

        ff = []
        if not fields_filter and len(self):
            ff.extend(self[0].keys())
        else:
            ff = fields_filter
        filtered_issues = list(
            map(lambda ffi: ffi.filtered_copy(ff), filtered_issues))
        return JQLResult(self.query, filtered_label, filtered_issues)


class JiraProject(JQLResult):
    """This subclass represents a project from Jira. It is really only a convenience class
        to wrap a JQL query that is intended to pull all issues from a project.

    """

    def __init__(self, project: JIRA.project, query_string: str = '', issues: List[JIRA.issue] = []) -> None:
        """Init a JiraProject

        Args:
            project (JiraProject): A JIRA project instance
            query_string (srt): The query used to grab this project data.
        """
        super().__init__(query_string, project.name, issues)
        self._key = project.key
        self._name = project.name

    @property
    def key(self) -> str:
        """
        str: `key`
            The project key as it is in Jira.
        """
        return self._key

    @property
    def name(self) -> str:
        """
        str: `name`
            The project name as it is in Jira.
        """
        return self._name


class Jira:
    """An Engineering Metrics wrapper for data we can harvest from Jira.
    """

    def __init__(self, jiraclient: JIRA) -> None:
        self._client = jiraclient
        self._datastore = {
            "issues": {},
            "projects": {}
        }

    # In order to retrieve the comments field we have to explicitly ask for it.
    # This means we have to explicitly ask for ALL fileds we are intereseted in. If
    # we are interested in a field that is not listed we have to add it.
    __ISSUES_FIELDS__ = [
        'assignee',
        'comment',
        'created',
        'customfield_10001',
        'description',
        'fixVersions',
        'issuelinks',
        'issuetype',
        'labels',
        'parent',
        'priority',
        'project',
        'resolution',
        'resolutiondate',
        'status',
        'summary',
        'updated'
    ]

    def _get_issues_for_projects(self, project_ids: List[str],  max_results: int = False, get_comments: bool = True) -> Dict[str, JiraProject]:

        issuefields = self.__ISSUES_FIELDS__.copy()
        if not get_comments:
            issuefields.remove('comment')
            
        issues_by_project = {}
        for pid in project_ids:
            pdata = self._client.project(pid)

            query_string = 'project = "{}" ORDER BY priority DESC'.format(pid)
            issues = self._client.search_issues(
                query_string,
                maxResults=max_results,
                expand='changelog',
                fields=issuefields
            )
            proj = JiraProject(pdata, query_string, issues)

            if len(proj):
                issues_by_project[pid] = proj

        return issues_by_project

    def populate_projects(self, projectids: List[str], max_results: int = False, get_comments: bool = True) -> Dict[str, JiraProject]:
        """Populate the Jira instance with data from the Jira app.

        Given a list of ids this method will build a dictionary containing issues from
        each project in the list. As well as returning the data to the callee, this method
        stores the results internally to facilitate the use of a range of helper methods
        to analyse the data.

        Args:
            projectids: A list of project ids for which you want to pull issues.
            max_results (optional): Limit the number of issues returned by the query.
            get_comments (optional): Retrieve all comments for Jira issues

        Returns:
            Dict[str, JiraProject]: A dictionary of JiraProjects. Each key will be the id for the corresponding project.
        """

        projects = self._get_issues_for_projects(projectids,  max_results, get_comments)
        self._datastore['projects'] = {
            **self._datastore['projects'], **projects}
        return projects

    def get_project_issues(self, projectid: str, max_results: int = False, get_comments: bool = True) -> JiraProject:
        """Get issues for a particular project key.

        Given a project key this method will retuen a list of issues from
        that project. As well as returning the data to the callee, this method
        stores the results internally to facilitate the use of a range of helper methods
        to analyse the data.

        Args:
            projectid: A project id for which you want to pull issues.
            max_results (optional): Limit the number of issues returned by the query.
            comments (optional): Retrieve all comments for Jira issues

        Returns:
            JiraProject: A list of JiraIssue instances.
        """
        project = self._get_issues_for_projects(
            [projectid],  max_results, get_comments).get(projectid, JQLResult(projectid, projectid))
        self._datastore[projectid] = project
        return project

    def populate_from_jql(self, query: str = None, max_results: int = False, label: str = "JQL", get_comments: bool = True) -> JQLResult:
        """Populate the Jira instance with data from the Jira app according to a JQL
        string.

        Given a JQL string this method will build a dictionary containing issues returned
        by executing the query. As well as retuning the data to the callee, this method
        stores the results internally to facilitate the use of a range of helper methods
        to analyse the data.

        Args:
            query: 
                The JQL query to perform against the Jira data.
            max_results:
                Limit the number of issues returned by the query.
            label (optional):
                A string label to store the query result internally. If not set the query
                result is stored under the key 'JQL' and overwrites any previous query results.
            comments (optional): 
                Retrieve all comments for Jira issues

        Returns:
            JQLResult: an instance of :py:class:`JQLResult`
        """
        
        if query == None:
            raise ValueError("query string is required to get issues")

        issuefields = self.__ISSUES_FIELDS__.copy()
        if not get_comments:
            issuefields.remove('comment')
              
        result = self._client.search_issues(
            query, maxResults=max_results, expand='changelog', fields=issuefields)
        query_result = JQLResult(query, label, result)
        self._datastore[query_result.label] = query_result
        return query_result

    def get_query_result(self, label: str = 'JQL') -> Dict[str, object]:
        """Get a cached JQL query result dictionary

        Args:
            label (optional): The label supplied with the original query

        Returns:
            JQLResult: an instance of :py:class:`JQLResult`

        """
        return self._datastore[label]

    def get_project(self, pid: str) -> JiraProject:
        """Get a cached project for a given pid

        Args:
            pid: The project key assigned by Jira.

        Returns:
            JiraProject: A project.
        """
        try:
            project = self._datastore['projects'][pid]
            return project
        except KeyError:
            return KeyError(f'No project with key {pid} in the cache. Have you called Jira.populate_projects(["{pid}"])?')

    @property
    def jiraclient(self) -> JIRA:
        """
        JIRA: `jiraclient`
            The instance of `Jira's python client <https://jira.readthedocs.io/en/master/>`_ wrapped by this adapter.
        """
        return self._client

    @property
    def projects(self) -> Dict[str, JiraProject]:
        """
        Dict[str, JiraProject]: `projects`
            A dictionary of Jira Project instances by project key e.g. INT
        """
        return self._datastore['projects']


def init_jira_adapter(jira_api_token: str = None, jira_oauth_config_path: str = None, jira_server_url: str = None, jira_username: str = None) -> Jira:
    """Set up an adapter to pull data from Jira. Handles the auth flow and returns an instance of the Jira
    class that facilitates metircs analysis around Jira data.

    Args:
        jira_api_token:
            The access token for Jira cloud (it's coming!)
        jira_oauth_config_path:
            A string path to the oauth config setup. Used for Jira server.
        jira_server_url:
            THe url of the jira instance to pull from.
        jira_username:
            The usename to use for authentication. Should be the username that owns the jira_api_token.
    Returns:
        Jira: An instance of the Jira adapter class
    """
    if jira_api_token and jira_username and jira_server_url:
        options = {
            'server': jira_server_url
        }
        return Jira(JIRA(options, basic_auth=(jira_username, jira_api_token)))

    if jira_oauth_config_path != None:
        path_to_config = os.path.join(jira_oauth_config_path,
                                      '.oauthconfig/.oauth_jira_config')

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
