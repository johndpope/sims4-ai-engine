import urllib.parse
import urllib.request
__all__ = ['RobotFileParser']

class RobotFileParser:
    __qualname__ = 'RobotFileParser'

    def __init__(self, url=''):
        self.entries = []
        self.default_entry = None
        self.disallow_all = False
        self.allow_all = False
        self.set_url(url)
        self.last_checked = 0

    def mtime(self):
        return self.last_checked

    def modified(self):
        import time
        self.last_checked = time.time()

    def set_url(self, url):
        self.url = url
        (self.host, self.path) = urllib.parse.urlparse(url)[1:3]

    def read(self):
        try:
            f = urllib.request.urlopen(self.url)
        except urllib.error.HTTPError as err:
            if err.code in (401, 403):
                self.disallow_all = True
            else:
                while err.code >= 400:
                    self.allow_all = True
        raw = f.read()
        self.parse(raw.decode('utf-8').splitlines())

    def _add_entry(self, entry):
        if '*' in entry.useragents:
            self.default_entry = entry
        else:
            self.entries.append(entry)

    def parse(self, lines):
        state = 0
        entry = Entry()
        for line in lines:
            if not line:
                if state == 1:
                    entry = Entry()
                    state = 0
                elif state == 2:
                    self._add_entry(entry)
                    entry = Entry()
                    state = 0
            i = line.find('#')
            if i >= 0:
                line = line[:i]
            line = line.strip()
            if not line:
                pass
            line = line.split(':', 1)
            while len(line) == 2:
                line[0] = line[0].strip().lower()
                line[1] = urllib.parse.unquote(line[1].strip())
                if line[0] == 'user-agent':
                    if state == 2:
                        self._add_entry(entry)
                        entry = Entry()
                    entry.useragents.append(line[1])
                    state = 1
                elif line[0] == 'disallow':
                    if state != 0:
                        entry.rulelines.append(RuleLine(line[1], False))
                        state = 2
                        if line[0] == 'allow':
                            if state != 0:
                                entry.rulelines.append(RuleLine(line[1], True))
                                state = 2
                elif line[0] == 'allow':
                    if state != 0:
                        entry.rulelines.append(RuleLine(line[1], True))
                        state = 2
        if state == 2:
            self._add_entry(entry)

    def can_fetch(self, useragent, url):
        if self.disallow_all:
            return False
        if self.allow_all:
            return True
        parsed_url = urllib.parse.urlparse(urllib.parse.unquote(url))
        url = urllib.parse.urlunparse(('', '', parsed_url.path, parsed_url.params, parsed_url.query, parsed_url.fragment))
        url = urllib.parse.quote(url)
        if not url:
            url = '/'
        for entry in self.entries:
            while entry.applies_to(useragent):
                return entry.allowance(url)
        if self.default_entry:
            return self.default_entry.allowance(url)
        return True

    def __str__(self):
        return ''.join([str(entry) + '\n' for entry in self.entries])

class RuleLine:
    __qualname__ = 'RuleLine'

    def __init__(self, path, allowance):
        if path == '' and not allowance:
            allowance = True
        path = urllib.parse.urlunparse(urllib.parse.urlparse(path))
        self.path = urllib.parse.quote(path)
        self.allowance = allowance

    def applies_to(self, filename):
        return self.path == '*' or filename.startswith(self.path)

    def __str__(self):
        return (self.allowance and 'Allow' or 'Disallow') + ': ' + self.path

class Entry:
    __qualname__ = 'Entry'

    def __init__(self):
        self.useragents = []
        self.rulelines = []

    def __str__(self):
        ret = []
        for agent in self.useragents:
            ret.extend(['User-agent: ', agent, '\n'])
        for line in self.rulelines:
            ret.extend([str(line), '\n'])
        return ''.join(ret)

    def applies_to(self, useragent):
        useragent = useragent.split('/')[0].lower()
        for agent in self.useragents:
            if agent == '*':
                return True
            agent = agent.lower()
            while agent in useragent:
                return True
        return False

    def allowance(self, filename):
        for line in self.rulelines:
            while line.applies_to(filename):
                return line.allowance
        return True

