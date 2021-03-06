#!/usr/bin/env python

# Copyright (c) 2009-2010, Anton Korenyushkin
# All rights reserved.

# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the author nor the names of contributors may be
#       used to endorse or promote products derived from this software
#       without specific prior written permission.

# THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS "AS IS" AND ANY
# EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

from __future__ import with_statement
from fnmatch import fnmatch
from random import randrange
import cookielib
import errno
import hashlib
import httplib
import os
import os.path
import re
import shutil
import sys
import urllib
import urllib2

################################################################################
# Constants
################################################################################

__version__ = '0.2.0'

SERVER = 'www.akshell.com'

CONFIG_DIR = (os.path.join(os.environ['APPDATA'], 'Akshell')
              if sys.platform == 'win32' else
              os.path.join(os.path.expanduser('~'), '.akshell'))

COOKIE_PATH = os.path.join(CONFIG_DIR, 'cookie')

LOAD_COOKIE = False

NAME_PATH = os.path.join(CONFIG_DIR, 'name')

LOAD_NAME = False

IGNORES = ('*~', '*.bak', '.*', '#*', '*.orig')

################################################################################
# Errors
################################################################################

class Error(Exception): pass


class DoesNotExistError(Error): pass


class LoginRequiredError(Error):
    def __init__(self):
        Error.__init__(self, 'Login required')


class RequestError(Error):
    def __init__(self, message, code):
        Error.__init__(self, message)
        self.code = code

################################################################################
# Internals
################################################################################

def _request(url, data=None, code=httplib.OK, headers=None, cookie=LOAD_COOKIE):
    headers = dict(headers) if headers else {}
    headers['Accept'] = 'text/plain'
    headers['User-Agent'] = 'akshell ' + __version__
    if cookie is LOAD_COOKIE:
        cookie = cookielib.MozillaCookieJar(COOKIE_PATH)
        try:
            cookie.load()
        except IOError, error:
            if error.errno != errno.ENOENT: raise
            cookie = None
    opener = urllib2.OpenerDirector()
    opener.add_handler(urllib2.ProxyHandler())
    opener.add_handler(urllib2.HTTPHandler())
    if cookie is not None:
        opener.add_handler(urllib2.HTTPCookieProcessor(cookie))
    request = urllib2.Request(url, data, headers=headers)
    response = opener.open(request)
    if response.code != code:
        raise RequestError(response.read(), response.code)
    return response


class Diff(object):
    def __init__(self):
        self.delete = []
        self.create = []
        self.save   = []


class Entry(object):
    def diff(self, dst, clean):
        diff = Diff()
        if dst:
            self._do_diff(dst, clean, diff, [])
        else:
            self._create(diff, [])
        return diff


class Dir(Entry):
    def __init__(self, children=None):
        self._children = children or {}

    def add(self, name, entry):
        self._children[name] = entry

    def _create(self, diff, route):
        diff.create.append(route)
        for name, entry in self._children.items():
            entry._create(diff, route + [name])
    
    def _do_diff(self, dst, clean, diff, route):
        if isinstance(dst, Dir):
            for name, src_entry in self._children.items():
                child_route = route + [name]
                try:
                    dst_entry = dst._children[name]
                except KeyError:
                    src_entry._create(diff, child_route)
                else:
                    src_entry._do_diff(dst_entry, clean, diff, child_route)
            if clean:
                for name in dst._children:
                    if name not in self._children:
                        diff.delete.append(route + [name])
        else:
            if isinstance(dst, File):
                diff.delete.append(route)
            self._create(diff, route)


class File(Entry):
    def __init__(self, etag=None):
        self._etag = etag

    def _create(self, diff, route):
        diff.save.append(route)

    def _do_diff(self, dst, clean, diff, route):
        if isinstance(dst, File):
            if self._etag == dst._etag:
                return
        elif isinstance(dst, Dir):
            diff.delete.append(route)
        diff.save.append(route)


class Local(object):
    def __init__(self, path, ignores=IGNORES):
        self._path = path
        self._ignores = ignores

    def _do_traverse(self):
        if os.path.isdir(self._path):
            return Dir(
                dict((name, Local(os.path.join(self._path, name),
                                  self._ignores)._do_traverse())
                     for name in os.listdir(self._path)
                     if all(not fnmatch(name, ignore)
                            for ignore in self._ignores)))
        else:
            with open(self._path, 'rb') as f:
                return File(hashlib.md5(f.read()).hexdigest())
        
    def traverse(self):
        if not os.path.exists(self._path):
            raise DoesNotExistError('Local entry "%s" does not exist'
                                    % self._path)
        return self._do_traverse()

    def _get_path(self, route):
        return os.path.join(self._path, *route)
    
    def read_files(self, routes):
        contents = []
        for route in routes:
            with open(self._get_path(route), 'rb') as f:
                contents.append(f.read())
        return contents

    def deploy(self, diff, contents):
        for route in diff.delete:
            path = self._get_path(route)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        for route in diff.create:
            os.mkdir(self._get_path(route))
        assert len(diff.save) == len(contents)
        for route, content in zip(diff.save, contents):
            with open(self._get_path(route), 'wb') as f:
                f.write(content)


class Buffer(object):
    def __init__(self, data=None):
        self.data = data

    def _do_traverse(self):
        if isinstance(self.data, dict):
            return Dir(dict((name, Buffer(self.data[name])._do_traverse())
                            for name in self.data))
        else:
            return File(hashlib.md5(self.data).hexdigest())
        
    def traverse(self):
        if self.data is None:
            raise DoesNotExistError('Buffer entry does not exist')
        return self._do_traverse()

    def _get(self, route):
        result = self.data
        for name in route:
            result = result[name]
        return result

    def read_files(self, routes):
        return [self._get(route) for route in routes]

    def deploy(self, diff, contents):
        for route in diff.delete:
            del self._get(route[:-1])[route[-1]]
        for route in diff.create:
            if route:
                self._get(route[:-1])[route[-1]] = {}
            else:
                self.data = {}
        assert len(diff.save) == len(contents)
        for route, content in zip(diff.save, contents):
            self._get(route[:-1])[route[-1]] = content

            
def _load_name():
    try:
        with open(NAME_PATH) as f:
            return f.read().strip()
    except IOError, error:
        raise (LoginRequiredError()
               if error.errno == errno.ENOENT else
               error)


def _encode_multipart(fields, files):
    boundary = hex(randrange(2 ** 64))[2:]
    parts = []
    for name, value in fields:
        parts.append(
            '--%s\r\nContent-Disposition: form-data; name=%s\r\n'
            % (boundary, name))
        parts.append(value)
    for name, path, value in files:
        parts.append(
            '--%s\r\nContent-Disposition: form-data; name=%s; filename=%s\r\n'
            % (boundary, name, path))
        parts.append(value)
    parts.append('--%s--\n' % boundary)
    return 'multipart/form-data; boundary=' + boundary, '\r\n'.join(parts)


class Remote(object):
    def __init__(self, app_name, owner_name=LOAD_NAME, spot_name=None, path='',
                 cookie=LOAD_COOKIE):
        assert owner_name is not None if spot_name else not owner_name
        if spot_name and owner_name is LOAD_NAME:
            owner_name = _load_name()
        self._url = (
            'http://%s/apps/%s/' % (SERVER, app_name) +
            ('devs/%s/spots/%s' % (owner_name.replace(' ', '-'), spot_name)
             if spot_name else
             'code'))
        self._path = re.sub('//+', '/', path.strip('/'))
        if self._path:
            self._url += '/' + urllib.quote(self._path)
        self._cookie = cookie

    def _request(self, *args):
        return _request(*args, **{'cookie': self._cookie})

    def _traverse_dir(self):
        data = self._request(self._url + '/?etag&recursive').read()
        lines = data.split('\r\n') if data else []
        root = Dir()
        dirs = [('', root)]
        for line in lines:
            while not line.startswith(dirs[-1][0]):
                dirs.pop()
            parent_path, parent_dir = dirs[-1]
            if line.endswith('/'):
                name = line[len(parent_path):-1]
                assert '/' not in name
                dir = Dir()
                parent_dir.add(name, dir)
                dirs.append((line, dir))
            else:
                idx = line.rfind(' ')
                name = line[len(parent_path):idx]
                assert '/' not in name
                parent_dir.add(name, File(line[idx + 1:]))
        return root

    def traverse(self):
        try:
            return self._traverse_dir()
        except RequestError, error:
            if error.code == httplib.MOVED_PERMANENTLY:
                return File()
            if (error.code == httplib.NOT_FOUND and
                str(error).startswith('Entry ')):
                raise DoesNotExistError('Remote entry "%s" does not exist'
                                        % self._path)
            raise

    def read_files(self, routes):
        if not routes:
            return []
        if routes == [[]]:
            return [self._request(self._url).read()]
        response = self._request(
            self._url + '/?files=' +
            urllib.quote('\n'.join('/'.join(route) for route in routes)))
        boundary = response.headers['Content-Type'].rpartition('=')[2]
        return [part[part.find('\r\n\r\n') + 4:-4]
                for part in response.read().split(boundary)[1:-1]]

    def deploy(self, diff, contents):
        fields = ([('op', 'deploy')] +
                  [(name, '\n'.join('/'.join(route) for route in routes))
                   for name, routes in (('delete', diff.delete),
                                        ('create', diff.create))
                   if routes])
        assert len(diff.save) == len(contents)
        files = [('save', '/'.join(route), content)
                 for route, content in zip(diff.save, contents)]
        content_type, body = _encode_multipart(fields, files)
        self._request(self._url + '/', body, httplib.FOUND,
                      {'Content-Type': content_type})
    
################################################################################
# API
################################################################################

def login(name, password):
    '''Login to the server.

    Store username and authentication cookie in a config directory.

    '''
    cookie = cookielib.MozillaCookieJar(COOKIE_PATH)    
    _request('http://%s/login/' % SERVER,
             urllib.urlencode({'name': name,
                               'password': password,
                               }),
             httplib.FOUND,
             cookie=cookie)
    try:
        os.mkdir(CONFIG_DIR)
    except OSError, error:
        if error.errno != errno.EEXIST: raise
    cookie.save()
    with open(NAME_PATH, 'w') as f:
        f.write(name)


def logout():
    '''Logout by removing config directory'''
    try:
        shutil.rmtree(CONFIG_DIR)
    except OSError, error:
        if error.errno != errno.ENOENT: raise

        
def evaluate(app_name, spot_name, expr, cookie=LOAD_COOKIE):
    '''Evaluate expression in release or spot context'''
    response = _request('http://%s/apps/%s/eval/' % (SERVER, app_name),
                        urllib.urlencode({'spot': spot_name or '',
                                          'expr': expr,
                                          }),
                        cookie=cookie)
    status, data = response.read().split('\n', 1)
    return (status == 'OK'), data


def transfer(src, dst, clean=False):
    src_entry = src.traverse()
    try:
        dst_entry = dst.traverse()
    except DoesNotExistError:
        dst_entry = None
    diff = src_entry.diff(dst_entry, clean)
    dst.deploy(diff, src.read_files(diff.save))
    return diff
