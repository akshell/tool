#!/usr/bin/env python
# -*- coding: utf-8 -*-

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
from getpass import getpass
import cStringIO
import coverage
import os.path
import shutil
import sys
import tempfile
import unittest
import urllib2

import coverage_color

script = akshell = None # To be set in main()


def _create_config():
    print '''\
For running akshell unit tests you need a test application.
If you already have one type your credentials, application name and
spot name in it below for config file generation.'''
    user = raw_input('User name: ')
    password = getpass('Password: ')
    app = raw_input('App name: ')
    spot = raw_input('Spot name: ')
    path = os.path.join(os.path.dirname(__file__), 'test_vars.py')
    with open(path, 'w') as f:
        f.write('''\
# Akshell test config file. Generated automatically.

USER = %s
PASSWORD = %s
APP = %s
SPOT = %s
''' % tuple(repr(var) for var in (user, password, app, spot)))
    print 'Config file "test_vars.py" was generated.'
    return user, password, app, spot


try:
    from test_vars import USER, PASSWORD, APP, SPOT
except ImportError:
    USER, PASSWORD, APP, SPOT = _create_config()


class _ToolTestCase(unittest.TestCase):
    def _launch(self, args, code=0, input=None, stream='stdout'):
        if type(args) in (str, unicode):
            args = args.split()
        assert stream in ('stdout', 'stderr')
        return_code = 0
        if input is not None:
            old_stdin = sys.stdin
            sys.stdin = cStringIO.StringIO(input)
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = cStringIO.StringIO()
        sys.stderr = cStringIO.StringIO()
        try:
            script.main(args)
        except SystemExit, system_exit:
            return_code = system_exit.code
        finally:
            result = (sys.stdout.getvalue() if stream == 'stdout' else
                      sys.stderr.getvalue())
            sys.stdout.close()
            sys.stderr.close()
            if input is not None:
                sys.stdin.close()
                sys.stdin = old_stdin
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        self.assertEqual(return_code, code)
        return result
    
    
class CommandTestCase(_ToolTestCase):
    def testHelp(self):
        main_help = self._launch([])
        self.assertEqual(self._launch('help'), main_help)
        self.assertEqual(self._launch('help'), main_help)
        login_help = self._launch('help login')
        self.assertEqual(self._launch('login --help'), login_help)
        get_help = self._launch('help get')
        self.assertEqual(self._launch('get --help'), get_help)
        self.assertEqual(self._launch('help login get'),
                         '\n'.join([login_help, get_help]))

    def testVersion(self):
        version = 'akshell ' + akshell.__version__ + '\n'
        self.assertEqual(self._launch('-v'), version)
        old_argv = sys.argv
        sys.argv = ['akshell', '--version']
        try:
            self.assertEqual(self._launch(None), version)
        finally:
            sys.argv = old_argv

    def testCommandErrors(self):
        self._launch('help no_such_command')
        self._launch('no_such_command', 1)

    def testLoginLogout(self):
        try:
            script.getpass = raw_input
            credentials = '%s\n%s\n' % (USER, PASSWORD)
            self._launch('login', input=credentials)
            self._launch('login', input=credentials)
            self._launch('logout')
            self._launch('logout')
            self._launch('login', input='%s\n%s \n' % (USER, PASSWORD), code=1)
            self._launch('login', input='')
            def interrupt(*args):
                raise KeyboardInterrupt
            script.getpass = interrupt
            self._launch('login', input=credentials, code=1)
            def raise_url_error(prompt_):
                raise urllib2.URLError(None)
            script.getpass = raise_url_error
            self._launch('login', input=credentials, code=1)
        finally:
            script.getpass = getpass

    def testGetPutEval(self):
        self._launch('get 1 2 3', code=1)
        self._launch('put app', input='n\n')
        self._launch('eval app 2+2', input='n\n')
        self._launch('eval 1 2 3', code=1)

        
def _write(path, data):
    with open(path, 'w') as f:
        f.write(data)


def _read(path):
    with open(path) as f:
        return f.read()

        
class WorkTestCase(_ToolTestCase):
    def setUp(self):
        akshell.login(USER, PASSWORD)
        self._dir = tempfile.mkdtemp()
        self._old_cwd = os.getcwd()
        os.chdir(self._dir)
        self._launch(['put', '-cf', APP, '.'])
        os.makedirs(os.path.join('dir', 'subdir'))
        _write(os.path.join('dir', 'hello.txt'), 'hello world')
        _write('__main__.js', 'var x = 42;')
        self._launch(['put', '-f', APP, '.'])
        self._launch(['put', '-c', '%s:%s' % (APP, SPOT), '.'])
        shutil.rmtree('dir')
        os.remove('__main__.js')

    def tearDown(self):
        os.chdir(self._old_cwd)
        shutil.rmtree(self._dir)

    def testGet(self):
        self._launch(['get', 'no-such-app'], code=1)
        delete, create, save = akshell.get(APP)
        self.assertEqual(delete, [])
        self.assertEqual(create, [['dir'], ['dir', 'subdir']])
        self.assertEqual(save, [['__main__.js'], ['dir', 'hello.txt']])
        self.assertEqual(_read(os.path.join('dir', 'hello.txt')), 'hello world')
        os.remove('__main__.js')
        os.mkdir('__main__.js')
        _write(os.path.join('dir', 'hello.txt'), 'wuzzup')
        self._launch(['get', APP, '.'])
        self.assertEqual(_read(os.path.join('dir', 'hello.txt')),
                         'hello world')
        os.rmdir(os.path.join('dir', 'subdir'))
        _write(os.path.join('dir', 'subdir'), '')
        os.mkdir('some_dir')
        _write('some_file', '')
        self._launch(['get', APP, '.'])
        self.assert_(os.path.exists('some_dir'))
        self.assert_(os.path.exists('some_file'))
        self._launch(['get', '-c', APP, '.'])
        self.assert_(not os.path.exists('some_dir'))
        self.assert_(not os.path.exists('some_file'))
        os.remove('__main__.js')
        self._launch(['get', APP + '/__main__.js'])
        self.assert_(os.path.isfile('__main__.js'))
        akshell.logout()
        self._launch(['get', '%s:%s@%s' % (APP, USER, SPOT)], code=1)

    def testGetSpot(self):
        self._launch(['get', '%s:%s@%s/dir' % (APP, USER, SPOT)])
        self.assert_(os.path.isdir('dir'))
        self._launch(['get', '%s:%s@%s' % (APP, USER, SPOT), SPOT])
        self.assert_(os.path.isdir(SPOT))
        shutil.rmtree(SPOT)
        self._launch(['get', '%s:%s' % (APP, SPOT), SPOT])
        self.assert_(os.path.isdir(SPOT))

    def testExceptions(self):
        self.assertRaises(AssertionError,
                          akshell.get,
                          APP, owner_name=USER)
        akshell.logout()
        self.assertRaises(akshell.LoginRequiredError,
                          akshell.get,
                          APP, spot_name=SPOT)

    def testPut(self):
        self._launch(['get', APP, '.'])
        self.assertEqual(
            self._launch(['put', '-qf', APP, '.', '-e', 'x']),
            '42\n')
        _write('file', 'some text')
        os.mkdir('some_dir')
        os.mkdir(os.path.join('some_dir', '.svn'))
        shutil.rmtree('dir')
        _write('backup~', '')
        _write('1.bak', '')
        _write('russian имя файла', '')
        output = self._launch(
            ['put', '-cfi', ':*~::::*.bak:.*::', APP, '.'])
        self.assert_('file' in output)
        self.assert_('some_dir' in output)
        self.assert_('dir' in output)
        self.assert_('.svn' not in output)
        self.assert_('backup~' not in output)
        self.assert_('1.bak' not in output)
        shutil.rmtree('some_dir')
        _write('some_dir', '')
        self.assert_('some_dir' in
                     self._launch(['put', '-f', APP, '.']))
        self._launch(['get', '-c', APP, '.'])
        self.assert_(os.path.exists('russian имя файла'))
        self.assert_(os.path.exists('backup~'))
        self._launch(['get', '-c', '-i', '', APP, '.'])
        self.assert_(not os.path.exists('backup~'))
        _write('another file', '')
        self.assert_('S another file' in
                     self._launch(['put', '-f', APP + '/another file']))

    def testEval(self):
        self.assertEqual(self._launch(['eval', '-f', APP, 'x']), '42\n')
        place = '%s:%s' % (APP, SPOT)
        self._launch(['eval', place, 'y=1'])
        self.assertEqual(self._launch(['eval', place, 'y']), '1\n')
        self.assert_('ReferenceError' in self._launch(['eval', '-f', APP, 'y']))
        

def suite():
    result = unittest.TestSuite()
    result.addTest(unittest.makeSuite(CommandTestCase))
    result.addTest(unittest.makeSuite(WorkTestCase))
    return result


def _process_coverage(module):
    path, statements_, missing_, missing_lines = coverage.analysis(module)
    with open('coverage_%s.html' % module.__name__, 'w') as f:
        coverage_color.colorize_file(path, f, missing_lines)

        
def main():
    try:
        cov_idx = sys.argv.index('--cov')
    except ValueError:
        collecting_coverage = False
    else:
        del sys.argv[cov_idx]
        coverage.start()
        collecting_coverage = True
    global akshell, script
    akshell = __import__('akshell')
    script = __import__('script')
    try:
        server_idx = sys.argv.index('--server')
    except ValueError:
        pass
    else:
        akshell.SERVER = sys.argv[server_idx + 1]
        del sys.argv[server_idx : server_idx + 2]
    try:
        unittest.main(defaultTest='suite')
    finally:
        if collecting_coverage:
            coverage.stop()
            _process_coverage(akshell)
            _process_coverage(script)
            coverage.report([akshell, script], show_missing=False)
            coverage.erase()
            
    
if __name__ == '__main__':
    main()
