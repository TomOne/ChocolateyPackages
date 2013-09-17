import re

from ..versions import version_sort, version_filter
from .json_api_client import JSONApiClient


# A predefined list of readme filenames to look for
_readme_filenames = [
    'readme',
    'readme.txt',
    'readme.md',
    'readme.mkd',
    'readme.mdown',
    'readme.markdown',
    'readme.textile',
    'readme.creole',
    'readme.rst'
]


class BitBucketClient(JSONApiClient):

    def download_info(self, url):
        """
        Retrieve information about downloading a package

        :param url:
            The URL of the repository, in one of the forms:
              https://bitbucket.org/{user}/{repo}
              https://bitbucket.org/{user}/{repo}/src/{branch}
              https://bitbucket.org/{user}/{repo}/#tags
            If the last option, grabs the info from the newest
            tag that is a valid semver version.

        :raises:
            DownloaderException: when there is an error downloading
            ClientException: when there is an error parsing the response

        :return:
            None if no match, False if no commit, or a dict with the following keys:
              `version` - the version number of the download
              `url` - the download URL of a zip file of the package
              `date` - the ISO-8601 timestamp string when the version was published
        """

        commit_info = self._commit_info(url)
        if not commit_info:
            return commit_info

        return {
            'version': commit_info['version'],
            'url': 'https://bitbucket.org/%s/get/%s.zip' % (commit_info['user_repo'], commit_info['commit']),
            'date': commit_info['timestamp']
        }

    def repo_info(self, url):
        """
        Retrieve general information about a repository

        :param url:
            The URL to the repository, in one of the forms:
              https://bitbucket.org/{user}/{repo}
              https://bitbucket.org/{user}/{repo}/src/{branch}

        :raises:
            DownloaderException: when there is an error downloading
            ClientException: when there is an error parsing the response

        :return:
            None if no match, or a dict with the following keys:
              `name`
              `description`
              `homepage` - URL of the homepage
              `author`
              `readme` - URL of the readme
              `issues` - URL of bug tracker
              `donate` - URL of a donate page
        """

        user_repo, branch = self._user_repo_branch(url)
        if not user_repo:
            return user_repo

        api_url = self._make_api_url(user_repo)

        info = self.fetch_json(api_url)

        issues_url = u'https://bitbucket.org/%s/issues' % user_repo

        return {
            'name': info['name'],
            'description': info['description'] or 'No description provided',
            'homepage': info['website'] or url,
            'author': info['owner'],
            'donate': u'https://www.gittip.com/on/bitbucket/%s/' % info['owner'],
            'readme': self._readme_url(user_repo, branch),
            'issues': issues_url if info['has_issues'] else None
        }

    def _commit_info(self, url):
        """
        Fetches info about the latest commit to a repository

        :param url:
            The URL to the repository, in one of the forms:
              https://bitbucket.org/{user}/{repo}
              https://bitbucket.org/{user}/{repo}/src/{branch}
              https://bitbucket.org/{user}/{repo}/#tags
            If the last option, grabs the info from the newest
            tag that is a valid semver version.

        :raises:
            DownloaderException: when there is an error downloading
            ClientException: when there is an error parsing the response

        :return:
            None if no match, False if no commit, or a dict with the following keys:
              `user_repo` - the user/repo name
              `timestamp` - the ISO-8601 UTC timestamp string
              `commit` - the branch or tag name
              `version` - the extracted version number
        """

        tags_match = re.match('https?://bitbucket.org/([^/]+/[^#/]+)/?#tags$', url)

        version = None

        if tags_match:
            user_repo = tags_match.group(1)
            tags_url = self._make_api_url(user_repo, '/tags')
            tags_list = self.fetch_json(tags_url)
            tags = version_filter(tags_list.keys(), self.settings.get('install_prereleases'))
            tags = version_sort(tags, reverse=True)
            if not tags:
                return False
            commit = tags[0]
            version = re.sub('^v', '', commit)

        else:
            user_repo, commit = self._user_repo_branch(url)
            if not user_repo:
                return user_repo

        changeset_url = self._make_api_url(user_repo, '/changesets/%s' % commit)
        commit_info = self.fetch_json(changeset_url)

        commit_date = commit_info['timestamp'][0:19]

        if not version:
            version = re.sub('[\-: ]', '.', commit_date)

        return {
            'user_repo': user_repo,
            'timestamp': commit_date,
            'commit': commit,
            'version': version
        }

    def _main_branch_name(self, user_repo):
        """
        Fetch the name of the default branch

        :param user_repo:
            The user/repo name to get the main branch for

        :raises:
            DownloaderException: when there is an error downloading
            ClientException: when there is an error parsing the response

        :return:
            The name of the main branch - `master` or `default`
        """

        main_branch_url = self._make_api_url(user_repo, '/main-branch')
        main_branch_info = self.fetch_json(main_branch_url, True)
        return main_branch_info['name']

    def _make_api_url(self, user_repo, suffix=''):
        """
        Generate a URL for the BitBucket API

        :param user_repo:
            The user/repo of the repository

        :param suffix:
            The extra API path info to add to the URL

        :return:
            The API URL
        """

        return 'https://api.bitbucket.org/1.0/repositories/%s%s' % (user_repo, suffix)

    def _readme_url(self, user_repo, branch, prefer_cached=False):
        """
        Parse the root directory listing for the repo and return the URL
        to any file that looks like a readme

        :param user_repo:
            The user/repo string

        :param branch:
            The branch to fetch the readme from

        :param prefer_cached:
            If a cached directory listing should be used instead of a new HTTP request

        :raises:
            DownloaderException: when there is an error downloading
            ClientException: when there is an error parsing the response

        :return:
            The URL to the readme file, or None
        """

        listing_url = self._make_api_url(user_repo, '/src/%s/' % branch)
        root_dir_info = self.fetch_json(listing_url, prefer_cached)

        for entry in root_dir_info['files']:
            if entry['path'].lower() in _readme_filenames:
                return 'https://bitbucket.org/%s/raw/%s/%s' % (user_repo,
                    branch, entry['path'])

        return None

    def _user_repo_branch(self, url):
        """
        Extract the username/repo and branch name from the URL

        :param url:
            The URL to extract the info from, in one of the forms:
              https://bitbucket.org/{user}/{repo}
              https://bitbucket.org/{user}/{repo}/src/{branch}

        :raises:
            DownloaderException: when there is an error downloading
            ClientException: when there is an error parsing the response

        :return:
            A tuple of (user/repo, branch name) or (None, None) if not matching
        """

        repo_match = re.match('https?://bitbucket.org/([^/]+/[^/]+)/?$', url)
        branch_match = re.match('https?://bitbucket.org/([^/]+/[^/]+)/src/([^/]+)/?$', url)

        if repo_match:
            user_repo = repo_match.group(1)
            branch = self._main_branch_name(user_repo)

        elif branch_match:
            user_repo = branch_match.group(1)
            branch = branch_match.group(2)

        else:
            return (None, None)

        return (user_repo, branch)