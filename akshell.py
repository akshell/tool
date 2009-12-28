#!/usr/bin/env python

# Copyright (c) 2009, Anton Korenyushkin
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
from getpass import getpass
from optparse import OptionParser, Option, SUPPRESS_HELP
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

__all__ = [
    'SERVER',
    'CONFIG_DIR',
    'COOKIE_PATH',
    'NAME_PATH',
    'FROM_SERVER',
    'TO_SERVER',
    'IGNORES',
    
    'Error',
    'LoginRequiredError',
    'DoesNotExistError',
    'RequestError',
    
    'login',
    'logout'
    'evaluate',
    'transfer',
    'get',
    'put'
    ]

__version__ = '0.1'

SERVER = 'www.akshell.com'

CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.akshell')

COOKIE_PATH = os.path.join(CONFIG_DIR, 'cookie')

NAME_PATH = os.path.join(CONFIG_DIR, 'name')

FROM_SERVER = True

TO_SERVER = False

IGNORES = ('*~', '*.bak', '.*', '#*')

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

def _request(url, data=None, code=httplib.OK, cookie=None, headers=None):
    headers = dict(headers) if headers else {}
    headers['Accept'] = 'text/plain'
    headers['User-Agent'] = 'akshell ' + __version__
    if cookie is None:
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


class _Diff(object):
    def __init__(self):
        self.delete = []
        self.create = []
        self.save   = []


class _Entry(object):
    def diff(self, dst, clean):
        diff = _Diff()
        if dst:
            self._do_diff(dst, clean, diff, [])
        else:
            self._create(diff, [])
        return diff


class _Dir(_Entry):
    def __init__(self, children=None):
        self._children = children or {}

    def add(self, name, entry):
        self._children[name] = entry

    def _create(self, diff, route):
        diff.create.append(route)
        for name, entry in self._children.items():
            entry._create(diff, route + [name])
    
    def _do_diff(self, dst, clean, diff, route):
        if isinstance(dst, _Dir):
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
            if isinstance(dst, _File):
                diff.delete.append(route)
            self._create(diff, route)


class _File(_Entry):
    def __init__(self, etag=None):
        self._etag = etag

    def _create(self, diff, route):
        diff.save.append(route)

    def _do_diff(self, dst, clean, diff, route):
        if isinstance(dst, _File):
            if self._etag == dst._etag:
                return
        elif isinstance(dst, _Dir):
            diff.delete.append(route)
        diff.save.append(route)


class _LocalCode(object):
    def __init__(self, path, ignores):
        self._path = path
        self._ignores = ignores

    def _do_traverse(self):
        if os.path.isdir(self._path):
            return _Dir(
                dict((name,
                      _LocalCode(os.path.join(self._path, name),
                                 self._ignores)._do_traverse())
                     for name in os.listdir(self._path)
                     if all(not fnmatch(name, ignore)
                            for ignore in self._ignores)))
        else:
            with open(self._path) as f:
                return _File(hashlib.md5(f.read()).hexdigest())
        
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
            with open(self._get_path(route)) as f:
                contents.append(f.read())
        return contents

    def deploy(self, diff, contents):
        for route in diff.delete:
            path = self._get_path(route)
            try:
                os.remove(path)
            except OSError, error:
                if error.errno != errno.EISDIR: raise
                shutil.rmtree(path)
        for route in diff.create:
            os.mkdir(self._get_path(route))
        assert len(diff.save) == len(contents)
        for route, content in zip(diff.save, contents):
            with open(self._get_path(route), 'w') as f:
                f.write(content)
    
    
def _get_own_name():
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


class _RemoteCode(object):
    def __init__(self, app_name, owner_name=None, spot_name=None, path=''):
        assert not owner_name or spot_name
        if spot_name and not owner_name:
            owner_name = _get_own_name()
        self._url = (
            'http://%s/apps/%s/' % (SERVER, app_name) +
            ('devs/%s/spots/%s' % (owner_name.lower().replace(' ', '-'),
                                   spot_name)
             if spot_name else
             'code'))
        self._path = re.sub('//+', '/', path.strip('/'))
        if self._path:
            self._url += '/' + urllib.quote(self._path)

    def _traverse_dir(self):
        data = _request(self._url + '/?etag&recursive').read()
        lines = data.split('\r\n') if data else []
        root = _Dir()
        dirs = [('', root)]
        for line in lines:
            while not line.startswith(dirs[-1][0]):
                dirs.pop()
            parent_path, parent_dir = dirs[-1]
            if line.endswith('/'):
                name = line[len(parent_path):-1]
                assert '/' not in name
                dir = _Dir()
                parent_dir.add(name, dir)
                dirs.append((line, dir))
            else:
                idx = line.rfind(' ')
                name = line[len(parent_path):idx]
                assert '/' not in name
                parent_dir.add(name, _File(line[idx + 1:]))
        return root

    def traverse(self):
        try:
            return self._traverse_dir()
        except RequestError, error:
            if error.code == httplib.MOVED_PERMANENTLY:
                return _File()
            # TODO: remove this 'if' when public version will be launched
            if error.code == httplib.FOUND:
                raise LoginRequiredError()
            if (error.code == httplib.NOT_FOUND and
                str(error).startswith('Entry ')):
                raise DoesNotExistError('Remote entry "%s" does not exist'
                                        % self._path)
            raise

    def read_files(self, routes):
        if not routes:
            return []
        if routes == [[]]:
            return [_request(self._url).read()]
        response = _request(
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
        _request(self._url + '/', body, httplib.FOUND,
                 headers={'Content-Type': content_type})
    
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
             cookie)
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

        
def evaluate(app_name, spot_name, expr):
    '''Evaluate expression in release or spot context'''
    response = _request('http://%s/apps/%s/eval/' % (SERVER, app_name),
                        urllib.urlencode({'spot': spot_name or '',
                                          'expr': expr,
                                          }))
    status, data = response.read().split('\n', 1)
    return (status == 'OK'), data


def transfer(direction, app_name, owner_name=None, spot_name=None,
             remote_path='', local_path='.',
             ignores=IGNORES, clean=False):
    local_code = _LocalCode(local_path, ignores)
    remote_code = _RemoteCode(app_name, owner_name, spot_name, remote_path)
    src_code, dst_code = ((remote_code, local_code)
                          if direction == FROM_SERVER else
                          (local_code, remote_code))
    src_entry = src_code.traverse()
    try:
        dst_entry = dst_code.traverse()
    except DoesNotExistError:
        dst_entry = None
    diff = src_entry.diff(dst_entry, clean)
    dst_code.deploy(diff, src_code.read_files(diff.save))
    return diff.delete, diff.create, diff.save
    

get = lambda *args, **kwds: transfer(FROM_SERVER, *args, **kwds)
put = lambda *args, **kwds: transfer(TO_SERVER, *args, **kwds)

################################################################################
# Commands
################################################################################

_HELP = '''\
Usage: akshell <command> [options] [args]

Available commands:
    login      login to the server and store credentials
    logout     logout from the server and remove stored credentials
    get        get data from app
    put        put data to app
    eval       evaluate expression in app

akshell is a tool for development access to http://akshell.com
'''


class _CommandOptionParser(OptionParser):
    def __init__(self, *args, **kwds):
        OptionParser.__init__(self, *args, **kwds)
        help_option = self.option_list[-1]
        assert help_option.get_opt_string() == '--help'
        help_option.help = SUPPRESS_HELP
        self.add_option('--server', default=SERVER, help=SUPPRESS_HELP)
        
    def format_option_help(self, formatter=None):
        return ('' if len(self.option_list) == 2 else
                OptionParser.format_option_help(self, formatter))

    def format_description(self, formatter):
        return self.get_description() + '\n'
    
    def format_help(self, formatter=None):
        if formatter is None:
            formatter = self.formatter
        assert self.usage and self.description and not self.epilog
        return ''.join([self.get_usage(), '\n',
                        self.format_description(formatter),
                        self.format_option_help(formatter),
                        ])

    def parse_args(self, args):
        global SERVER
        opts, args = OptionParser.parse_args(self, args)
        SERVER = opts.server
        return opts, args

    
def help_command(args):
    if not args:
        print _HELP,
        return
    is_first = True
    for command in args:
        try:
            command_handler = _command_handlers[command]
        except KeyError:
            sys.stderr.write('"%s": unknown command\n' % command)
        else:
            if not is_first:
                print
            try:
                command_handler(['--help',])
            except SystemExit, error:
                assert not error.code
            is_first = False
    
    
def login_command(args):
    parser = _CommandOptionParser(
        usage='akshell login',
        description='Login to the server and store credentials locally.')
    parser.parse_args(args)
    try:
        name = raw_input('Name: ')
        password = getpass('Password: ')
    except EOFError:
        print
        return
    login(name, password)

    
def logout_command(args):
    parser = _CommandOptionParser(
        usage='akshell logout',
        description='Logout from the server and remove stored credentials.')
    parser.parse_args(args)
    logout()
    

def _parse_app_owner_spot(string):
    try:
        app, owner_spot = string.split(':', 1)
    except ValueError:
        return string, None, None
    try:
        owner, spot = owner_spot.split('@', 1)
    except ValueError:
        return app, None, owner_spot
    return app, owner, spot


def _confirm(question):
    return raw_input(question + ' [y/n]? ') in ('y', 'yes')


_FORCE_OPTION = Option(
    '-f', '--force',
    default=False, action='store_true',
    help='Don\'t ask for confirmation of release code actions')


def _transfer_command(direction, args, command_name, descr_title):
    parser = _CommandOptionParser(
        usage=('Usage: akshell %s [options] '
               'APP[:[OWNER@]SPOT][/REMOTE_PATH] [LOCAL_PATH]'
               % command_name),
        description=descr_title + '''
Unless "quiet" option is set print deleted entries (D mark),
created directories (C mark) and saved files (S mark).
LOCAL_PATH defaults to REMOTE_PATH base name if avaliable or
current directory otherwise.
''',
        option_list=(Option('-c', '--clean',
                            default=False, action='store_true',
                            help='''\
Remove destination entries which don't have corresponding sources'''),
                     Option('-q', '--quiet',
                            default=False, action='store_true',
                            help='Print nothing'),
                     Option('-i', '--ignore',
                            help='''\
colon separated list of ignored filename wildcards, defaults to "%s"'''
                            % ':'.join(IGNORES)),
                     ))
    if direction == TO_SERVER:
        parser.add_option(_FORCE_OPTION)
        parser.add_option('-e', '--expr',
                          help='''\
Evaluate EXPR after put, print a value or an exception''')
    opts, args = parser.parse_args(args)
    if not args or len(args) > 2:
        sys.stderr.write('"%s" command requires 1 or 2 arguments.\n'
                         % command_name)
        sys.exit(1)
    app_owner_spot, sep_, remote_path = args[0].partition('/')
    app_name, owner_name, spot_name = _parse_app_owner_spot(app_owner_spot)
    remote_path = remote_path.strip('/')
    local_path = args[1] if len(args) > 1 else remote_path.rpartition('/')[2]
    ignores = (IGNORES if opts.ignore is None else
               [ignore for ignore in opts.ignore.split(':') if ignore])
    if (direction == TO_SERVER and
        not (spot_name or opts.force or _confirm('Put release code'))):
        return
    delete, create, save = transfer(
        direction, app_name, owner_name, spot_name,
        remote_path, local_path or '.',
        ignores, opts.clean)
    if not opts.quiet:
        for prefix, routes in (('D', delete), ('C', create), ('S', save)):
            for route in routes:
                print prefix, (os.path.join(local_path, *route)
                               if direction == FROM_SERVER else
                               '/'.join(([remote_path] if remote_path else []) +
                                        route))
    if getattr(opts, 'expr', None):
        print evaluate(app_name, spot_name, opts.expr)[1]
            

def get_command(args):
    _transfer_command(FROM_SERVER,
                      args,
                      'get',
                      'Get release or spot code from the server.')


def put_command(args):
    _transfer_command(TO_SERVER,
                      args,
                      'put',
                      'Put release or spot code to the server.')


def eval_command(args):
    parser = _CommandOptionParser(
        usage='Usage: akshell eval APP[:SPOT] EXPR',
        description='''\
Evaluate EXPR in release or spot version of application.
Print a value or an exception occured.
''',
        option_list=(_FORCE_OPTION,))
    opts, args = parser.parse_args(args)
    if len(args) != 2:
        sys.stderr.write('"eval" command requires 2 arguments\n')
        sys.exit(1)
    try:
        app_name, spot_name = args[0].split(':', 1)
    except ValueError:
        app_name, spot_name = args[0], None
        if not (opts.force or _confirm('Evaluate in release code')):
            return
    print evaluate(app_name, spot_name, args[1])[1]
    

_command_handlers = {'login': login_command,
                     'logout': logout_command,
                     'get': get_command,
                     'put': put_command,
                     'eval': eval_command,
                     'help': help_command,
                     }
    
################################################################################
# main()
################################################################################

def main(args=None):
    if args is None:
        args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print _HELP,
        return
    if args[0] in ('-v', '--version'):
        print 'akshell', __version__
        return
    command = args[0]
    try:
        command_handler = _command_handlers[command]
    except KeyError:
        sys.stderr.write('''\
Unknown command: '%s'
Type 'akshell help' for usage.
''' % command)
        sys.exit(1)
    try:
        command_handler(args[1:])
        return
    except Error, error:
        sys.stderr.write(str(error) + '\n')
    except KeyboardInterrupt:
        sys.stderr.write('\nInterrupted!\n')
    except urllib2.URLError, error:
        sys.stderr.write(str(error.reason) + '\n')
    sys.exit(1)


if __name__ == '__main__': main()
