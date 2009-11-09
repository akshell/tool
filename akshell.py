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

from fnmatch import fnmatch
from getpass import getpass
from optparse import OptionParser, Option, SUPPRESS_HELP
import cookielib
import errno
import hashlib
import httplib
import os
import os.path
import shutil
import stat
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
    
    'Error',
    'LoginRequiredError',
    'MismatchError',
    'RequestError',
    
    'login',
    'logout'
    
    'Options',
    'Callbacks',
    'AppData',
    ]

__version__ = '0.1'

SERVER = 'www.akshell.localhost:8000'

CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.akshell')

COOKIE_PATH = os.path.join(CONFIG_DIR, 'cookie')

NAME_PATH = os.path.join(CONFIG_DIR, 'name')

################################################################################
# Errors
################################################################################

class Error(Exception): pass

class RequestError(Error): pass

class MismatchError(Error): pass

class LoginRequiredError(Error): pass

################################################################################
# _make_request()
################################################################################

class _Request(urllib2.Request):
    def __init__(self, url, data=None, method=None, *args, **kwds):
        urllib2.Request.__init__(self, url, data, *args, **kwds)
        self._method = method

    def get_method(self):
        return (urllib2.Request.get_method(self)
                if self._method is None else
                self._method)

    
def _make_request(url, data=None, method=None, headers=None,
                  code=None, cookie=None):
    headers = {'Accept': 'text/plain'} if headers is None else headers.copy()
    headers['User-Agent'] = 'akshell ' + __version__
    if cookie is None:
        cookie = cookielib.MozillaCookieJar(COOKIE_PATH)
        try:
            cookie.load()
        except IOError as error:
            if error.errno != errno.ENOENT: raise
            cookie = None
    opener = urllib2.OpenerDirector()
    opener.add_handler(urllib2.ProxyHandler())
    opener.add_handler(urllib2.HTTPHandler())
    if cookie is not None:
        opener.add_handler(urllib2.HTTPCookieProcessor(cookie))
    request = _Request(url, data, method, headers)
    response = opener.open(request)
    if code is not None and response.code != code:
        raise RequestError(response.read())
    return response
    
################################################################################
# login() & logout()
################################################################################

def login(name, password):
    '''Login to the server.

    Store username and authentication cookie in a config directory.

    '''
    cookie = cookielib.MozillaCookieJar(COOKIE_PATH)    
    response = _make_request('http://%s/login/' % SERVER,
                             urllib.urlencode({'name': name,
                                               'password': password,
                                               }),
                             method='POST',
                             cookie=cookie)
    if response.code != httplib.FOUND:
        raise RequestError(response.read())
    try:
        os.mkdir(CONFIG_DIR)
    except OSError as error:
        if error.errno != errno.EEXIST: raise
    cookie.save()
    f = open(NAME_PATH, 'w')
    try:
        f.write(name + '\n')
    finally:
        f.close()


def logout():
    '''Logout by removing config directory'''
    try:
        shutil.rmtree(CONFIG_DIR)
    except OSError as error:
        if error.errno != errno.ENOENT: raise

################################################################################
# Entries
################################################################################

class _Entry(object):
    def __init__(self, place):
        self.place = place
        

class _SourceEntry(_Entry):
    pass


class _SourceFile(_SourceEntry):
    is_dir = False
    
    def __init__(self, place, data):
        _SourceEntry.__init__(self, place)
        self.data = data
        

class _SourceDir(_SourceEntry):
    is_dir = True
    
    def __init__(self, place, names):
        _SourceEntry.__init__(self, place)
        self.names = names

        
class _DestEntry(_Entry):
    def take(self, source, options): raise NotImplemented()

    def _force(self, source, options):
        self.place.delete()
        _EmptyDest(self.place).take(source, options)
        
    
class _DestFile(_DestEntry):
    def take(self, source, options):
        if source.is_dir:
            if options.force:
                self._force(source, options)
            else:
                self.place.raise_error(MismatchError,
                                       'expected directory, file found')
        else:
            self.place.put(source.data)
            

class _DestDir(_DestEntry):
    def take(self, source, options):
        if not source.is_dir:
            if options.force:
                self._force(source, options)
            else:
                self.place.raise_error(MismatchError,
                                       'expected file, directory found')
        else:
            if options.clean:
                names = self.place.get().names
                for name in names:
                    if (name not in source.names and
                        not options.is_ignored(name)):
                        self.place.get_child(name).delete()
            for name in source.names:
                if not options.is_ignored(name):
                    _deploy(source.place.get_child(name),
                            self.place.get_child(name),
                            options)
                

class _EmptyDest(_DestEntry):
    def take(self, source, options):
        if source.is_dir:
            self.place.create_as_dir()
            for name in source.names:
                if not options.is_ignored(name):
                    dest = _EmptyDest(self.place.get_child(name))
                    dest.take(source.place.get_child(name).get(), options)
        else:
            self.place.put(source.data)
                

def _deploy(from_place, to_place, options):
    source = from_place.get(etag=to_place.get_etag())
    if source is None:
        return
    dest = to_place.head(etag=from_place.get_etag())
    if dest is None:
        return
    dest.take(source, options)

################################################################################
# Places
################################################################################

class _Place(object):
    @staticmethod
    def _with_callback(name):
        def decorator(func):
            def decorated_func(self, *args, **kwds):
                result = func(self, *args, **kwds)
                getattr(self._callbacks, name)(self._path)
                return result
            return decorated_func
        return decorator

    def __init__(self, path, callbacks):
        self._path = path
        self._callbacks = callbacks

    def raise_error(self, cls, msg):
        raise cls('%s: %s' % (self._path, msg))

    def get_etag(self): raise NotImplemented()
    
    def get(self, etag=None): raise NotImplemented()

    def head(self, etag=None): raise NotImplemented()

    def put(self, data): raise NotImplemented()

    def delete(self): raise NotImplemented()

    def create_as_dir(self): raise NotImplemented()

    def get_child(self, name): raise NotImplemented()


class _RemotePlace(_Place):
    def __init__(self, base_url, path, callbacks):
        _Place.__init__(self, path, callbacks)
        self._base_url = base_url
        self._etag = None

    def _get_url(self):
        return '%s/%s' % (self._base_url, self._path)

    def _path_is_dir(self):
        return not self._path or self._path.endswith('/')

    def get_etag(self):
        return self._etag

    def _retrieve(self, method, etag):
        headers = {'Accept': 'text/plain, application/octet-stream'}
        if etag is not None:
            headers['If-None-Match'] = etag
        response = _make_request(self._get_url(),
                                 method=method,
                                 headers=headers)
        if response.code == httplib.MOVED_PERMANENTLY:
            self._path = response.headers['Location'][len(self._base_url) + 1:]
        return response
    
    def get(self, etag=None):
        response = self._retrieve('GET', etag)
        if response.code == httplib.MOVED_PERMANENTLY:
            return self.get(etag)
        if response.code == httplib.NOT_MODIFIED:
            return None
        data = response.read()
        if response.code != httplib.OK:
            raise RequestError(data)
        if self._path_is_dir():
            return _SourceDir(self, [name for name in data.split('\n') if name])
        else:
            self._etag = response.headers['ETag']
            return _SourceFile(self, data)
        
    def head(self, etag=None):
        response = self._retrieve('HEAD', etag)
        if response.code == httplib.NOT_MODIFIED:
            return None
        if response.code == httplib.NOT_FOUND:
            return _EmptyDest(self)
        if response.code not in (httplib.OK, httplib.MOVED_PERMANENTLY):
            raise RequestError(self._retrieve('GET', etag).read())
        return (_DestDir(self) if self._path_is_dir() else
                _DestFile(self))

    @_Place._with_callback('save')
    def put(self, data):
        _make_request(self._get_url(), data, method='PUT', code=httplib.OK)

    @_Place._with_callback('delete')
    def delete(self):
        _make_request(self._get_url(), method='DELETE', code=httplib.OK)

    @_Place._with_callback('create')
    def create_as_dir(self):
        parent_path, separator_, name = self._path.rstrip('/').rpartition('/')
        assert name
        parent_url = '%s/%s' % (self._base_url, parent_path)
        data = urllib.urlencode({'action': 'create_entry',
                                 'type': 'dir',
                                 'name': name,
                                 })
        _make_request(parent_url, data, method='POST', code=httplib.FOUND)

    def get_child(self, name):
        quoted_name = urllib.quote(name)
        return _RemotePlace(self._base_url,
                            (self._path +
                             ('' if self._path_is_dir() else '/') +
                             quoted_name),
                            self._callbacks)
        
            
class _LocalPlace(_Place):
    def __init__(self, path, callbacks):
        _Place.__init__(self, path, callbacks)
        self._data = None
        self._etag = None
        
    def _read(self):
        f = open(self._path, 'rb')
        try:
            return f.read()
        finally:
            f.close()
            
    def get_etag(self):
        if self._data is None:
            try:
                self._data = self._read()
            except IOError as error:
                if error.errno not in (errno.EISDIR, errno.ENOENT): raise
                return None
        if self._etag is None:
            self._etag = hashlib.md5(self._data).hexdigest()
        return self._etag
    
    def get(self, etag=None):
        assert etag is None
        if self._data is None:
            try:
                self._data = self._read()
            except IOError as error:
                if error.errno != errno.EISDIR: raise
                return _SourceDir(self, os.listdir(self._path))
        return _SourceFile(self, self._data)

    def head(self, etag=None):
        # If we are here etags are not equal
        try:
            mode = os.stat(self._path).st_mode
        except OSError as error:
            if error.errno != errno.ENOENT: raise
            return _EmptyDest(self)
        if stat.S_ISDIR(mode):
            return _DestDir(self)
        return _DestFile(self)

    @_Place._with_callback('save')
    def put(self, data):
        f = open(self._path, 'wb')
        try:
            f.write(data)
        finally:
            f.close()

    @_Place._with_callback('delete')
    def delete(self):
        try:
            os.remove(self._path)
        except OSError as error:
            if error.errno != errno.EISDIR: raise
            shutil.rmtree(self._path)

    @_Place._with_callback('create')
    def create_as_dir(self):
        os.mkdir(self._path)

    def get_child(self, name):
        return _LocalPlace(os.path.join(self._path, name), self._callbacks)
    
################################################################################
# Options, Callbacks, EvalResult, AppData
################################################################################
    
class Options(object):
    '''Options of get and put AppData methods'''
    def __init__(self, force=False, clean=False, ignores=None):
        self.force = force
        self.clean = clean
        self._ignores = ignores or []

    def is_ignored(self, name):
        for wildcard in self._ignores:
            if fnmatch(name, wildcard):
                return True
        return False


class Callbacks(object):
    '''Callbacks of get and put AppData methods.

    Callback events:
      - save: file was saved
      - create: directory was created
      - delete: file or directory was deleted

    '''
    def __init__(self,
                 save=lambda path: None,
                 create=lambda path: None,
                 delete=lambda path: None):
        self.save = save
        self.create = create
        self.delete = delete
        
        
def _get_dev_name():
    try:
        f = open(NAME_PATH)
    except IOError as error:
        if error.errno != errno.ENOENT: raise
        raise LoginRequiredError('Login required')
    try:
        return f.read().strip()
    finally:
        f.close()

        
class AppData(object):
    '''Application data accessor'''
    
    def __init__(self, app_name, spot_name=None, owner_name=None):
        assert owner_name is None or spot_name is not None
        if owner_name is None and spot_name is not None:
            owner_name = _get_dev_name()
        self._app_name = app_name
        self._spot_name = spot_name
        self._owner_name = owner_name

    def _get_base_url(self):
        return ('http://%s/apps/%s/' % (SERVER, self._app_name) +
                ('devs/%s/spots/%s' % (self._owner_name, self._spot_name)
                 if self._spot_name else
                 'release'))
                          
        
    def get(self, remote_path, path, options=Options(), callbacks=Callbacks()):
        '''Get the application data to a local storage'''
        _deploy(_RemotePlace(self._get_base_url(),
                             urllib.quote(remote_path),
                             callbacks),
                _LocalPlace(path, callbacks),
                options)

    def put(self, remote_path, path, options=Options(), callbacks=Callbacks()):
        '''Put data to the application from a local storage'''
        _deploy(_LocalPlace(path, callbacks),
                _RemotePlace(self._get_base_url(),
                             urllib.quote(remote_path),
                             callbacks),
                options)

    def evaluate(self, expr):
        '''Evaluate expression in context of this application data'''
        eval_url = ('http://%s/apps/%s/devs/%s/eval/'
                    % (SERVER,
                       self._app_name,
                       (self._owner_name if self._owner_name else
                        _get_dev_name())))
        data = urllib.urlencode({
                'data': 'spot' if self._spot_name else 'release',
                'spot_name': self._spot_name if self._spot_name else '',
                'expr': expr,
                })
        response = _make_request(eval_url, data, code=httplib.OK)
        status, data = response.read().split('\n', 1)
        return (status == 'OK'), data

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
        
    def format_option_help(self, formatter=None):
        return ('' if len(self.option_list) == 1 else
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

    
def help_command(args):
    if not args:
        print _HELP,
        return
    is_first = True
    for command in args:
        try:
            command_handler = _command_handlers[command]
        except KeyError:
            sys.stderr.write('"%s": unknown command' % command)
        else:
            if not is_first:
                print
            try:
                command_handler(['--help',])
            except SystemExit as error:
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
    

def _make_print_callback(prefix):
    def callback(path):
        print prefix, path
    return callback


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


def _get_put_command(args, command_name, descr_title, app_data_method):
    default_ignores = ('*~', '*.bak', '.*', '#*')
    parser = _CommandOptionParser(
        usage=('Usage: akshell %s [options] '
               'APP[:[OWNER@]SPOT][/REMOTE_PATH] [LOCAL_PATH]'
               % command_name),
        description=descr_title + '''
Unless "quiet" option is set print saved files (S mark), created
directories (C mark) and deleted entries if "force" or "clean" is set
(D mark).
If LOCAL_PATH is omited the first avaliable of REMOTE_PATH base name,
SPOT and APP is used.
''',
        option_list=(Option('-f', '--force',
                            default=False, action='store_true',
                            help='''\
Remove destination entries on file-directory and directory-file mismatch;
use with caution!'''),
                     Option('-c', '--clean',
                            default=False, action='store_true',
                            help='''\
Remove destination entries which don't have corresponding sources;
use with caution!'''),
                     Option('-q', '--quiet',
                            default=False, action='store_true',
                            help='Print nothing'),
                     Option('-i', '--ignore',
                            help='''\
colon separated list of ignored filename wildcards, defaults to "%s"'''
                            % ':'.join(default_ignores)),
                     ))
    if command_name == 'put':
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
    app_data = AppData(app_name, spot_name, owner_name)
    callbacks = (Callbacks() if opts.quiet else
                 Callbacks(save=_make_print_callback('S  '),
                           create=_make_print_callback('C  '),
                           delete=_make_print_callback('D  '),
                           ))
    options = Options(force=opts.force, clean=opts.clean,
                      ignores=([wildcard
                                for wildcard in opts.ignore.split(':')
                                if wildcard]
                               if opts.ignore is not None else
                               default_ignores))
    path = (args[1] if len(args) > 1 else
            os.path.basename(remote_path.rstrip('/')) or
            spot_name or
            app_name)
    app_data_method(app_data, remote_path, path,
                    options, callbacks)
    if getattr(opts, 'expr', None):
        print app_data.evaluate(opts.expr)[1]
            

def get_command(args):
    _get_put_command(args,
                     'get',
                     '''\
Get files from release or spot application data on http://akshell.com.''',
                     AppData.get)


def put_command(args):
    _get_put_command(args,
                     'put',
                     '''\
Put files to release or spot application data on http://akshell.com.''',
                     AppData.put)


def eval_command(args):
    parser = _CommandOptionParser(
        usage='Usage: akshell eval APP[:[OWNER@]SPOT] EXPR',
        description='''\
Evaluate EXPR in release or spot version of application.
Print a value or an exception occured.
''')
    opts_, args = parser.parse_args(args)
    if len(args) != 2:
        sys.stderr.write('"eval" command requires 2 arguments\n')
        sys.exit(1)
    app_name, owner_name, spot_name = _parse_app_owner_spot(args[0])
    print AppData(app_name, spot_name, owner_name).evaluate(args[1])[1]
    

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
    except Error as error:
        sys.stderr.write(str(error) + '\n')
    except KeyboardInterrupt:
        sys.stderr.write('\nInterrupted!\n')
    except urllib2.URLError as error:
        sys.stderr.write(str(error.reason) + '\n')
    sys.exit(1)


if __name__ == '__main__': main()
