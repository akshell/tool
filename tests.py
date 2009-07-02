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

from getpass import getpass
import cStringIO
import coverage
import errno
import os.path
import shutil
import sys
import tempfile
import unittest

import coverage_color


try:
    from test_vars import USER, PASSWORD, APP, SPOT
except ImportError:
    print '''\
For running akshell unit tests you need a test application.
If you already have one type your credentials, application name and
spot name in it below for config file generation.'''
    USER = raw_input('User name: ')
    PASSWORD = getpass('Password: ')
    APP = raw_input('App name: ')
    SPOT = raw_input('Spot name: ')
    f = open(os.path.join(os.path.dirname(__file__), 'test_vars.py'), 'w')
    try:
        f.write('''\
# Akshell test config file. Generated automatically.

USER = %s
PASSWORD = %s
APP = %s
SPOT = %s
''' % tuple(repr(var) for var in (USER, PASSWORD, APP, SPOT)))
    finally:
        f.close()
    print "Config file 'test_vars.py' was generated."


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
            akshell.main(args)
        except SystemExit as system_exit:
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
        help = self._launch([])
        self.assertEqual(self._launch('help'), help)
        self.assertEqual(self._launch('help'), help)
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
            akshell.getpass = lambda prompt, stream_: raw_input(prompt)
            credentials = '%s\n%s\n' % (USER, PASSWORD)
            self._launch('login', input=credentials)
            self._launch('login', input=credentials)
            self._launch('logout')
            self._launch('logout')
            self._launch('login', input='%s\n%s \n' % (USER, PASSWORD), code=1)
            self._launch('login', input='')
            def interrupt(*args):
                raise KeyboardInterrupt
            akshell.getpass = interrupt
            self._launch('login', input=credentials, code=1)
            def raise_exception(*args):
                raise Exception('wuzzup')
            akshell.getpass = raise_exception
            self.assertEqual(
                self._launch('login', input=credentials,
                             code=1, stream='stderr'),
                'wuzzup\n')
        finally:
            akshell.getpass = getpass

    def testGetPut(self):
        self._launch('get 1 2 3', code=1)
        self._launch('get -l unknown test', code=1)

    def testEval(self):
        self._launch('eval 1 2 3', code=1)

        
def _get_path(*entries):
    return os.path.join('.', *entries)

        
def _write(path, data):
    f = open(path, 'w')
    try:
        f.write(data)
    finally:
        f.close()


def _read(path):
    f = open(path)
    try:
        return f.read()
    finally:
        f.close()

        
class WorkTestCase(_ToolTestCase):
    def setUp(self):
        akshell.login(USER, PASSWORD)
        self._dir = tempfile.mkdtemp()
        self._old_cwd = os.getcwd()
        os.chdir(self._dir)
        os.makedirs(_get_path('code', 'dir', 'subdir'))
        os.makedirs(_get_path('media', 'templates'))
        _write(_get_path('code', 'dir', 'hello.txt'), 'hello world')
        _write(_get_path('code', 'main.js'), 'var x = 42;')
        _write(_get_path('media', 'templates', 'test.txt'), 'test')
        self._launch(['put', '-fc', APP, self._dir])
        self._launch(['put', '-fcs', SPOT, APP, self._dir])
        shutil.rmtree(_get_path('code'))
        shutil.rmtree(_get_path('media'))

    def tearDown(self):
        os.chdir(self._old_cwd)
        shutil.rmtree(self._dir)

    def testGet(self):
        files = set()
        dirs = set()
        callbacks = akshell.Callbacks(save=lambda path: files.add(path),
                                      create=lambda path: dirs.add(path))
        akshell.logout()
        akshell.AppData(APP).get('code', '', '.', callbacks=callbacks)
        self.assertEqual(files, set([_get_path('main.js'),
                                     _get_path('dir', 'hello.txt')]))
        self.assertEqual(dirs, set([_get_path('dir'),
                                    _get_path('dir', 'subdir')]))
        self.assertEqual(_read(_get_path('dir', 'hello.txt')),
                         'hello world')
        os.remove('main.js')
        os.mkdir('main.js')
        _write(_get_path('dir', 'hello.txt'), 'wuzzup')
        self._launch(['get', APP, '-l', 'code', '.'], code=1)
        self._launch(['get', APP, '-f', '-l', 'code', '.'])
        os.rmdir(_get_path('dir', 'subdir'))
        _write(_get_path('dir', 'subdir'), '')
        self._launch(['get', APP, '-l', 'code', '.'], code=1)
        os.mkdir('some_dir')
        _write('some_file', '')
        self._launch(['get', APP, '-f', '-l', 'code', '.'])
        self.assert_(os.path.exists('some_dir'))
        self.assert_(os.path.exists('some_file'))
        self._launch(['get', APP, '-c', '-l', 'code', '.'])
        self.assert_(not os.path.exists('some_dir'))
        self.assert_(not os.path.exists('some_file'))
        os.remove('main.js')
        shutil.rmtree('dir')
        self.assert_(not os.listdir('.'))
        self._launch(['get', APP])
        self._launch(['get', APP])
        self.assert_(os.path.isdir(APP))
        shutil.rmtree(APP)
        self.assertEqual(
            set(string.split()[1] for string in
                self._launch(['get', APP, '-l', 'media']).split('\n')
                if string),
            set(['media', 'media/templates', 'media/templates/test.txt']))
        shutil.rmtree('media')

    def testGetSpot(self):
        self._launch(['get', APP,
                      '-s', '%s:%s' % (USER, SPOT),
                      '-l', 'code:dir',
                      ])
        self.assert_(os.path.isdir('dir'))
        shutil.rmtree('dir')
        self._launch(['get', APP,
                      '-s', '%s:%s' % (USER, SPOT),
                      '-l', 'code',
                      ])
        self.assert_(os.path.isdir('code'))
        shutil.rmtree('code')

    def testExceptions(self):
        spot_data = akshell.AppData(APP, spot_name=SPOT)
        akshell.logout()
        self.assertRaises(akshell.RequestError,
                          lambda: spot_data.get('code', '', '.'))
        self.assertRaises(akshell.RequestError,
                          lambda: spot_data.put('code', '', '.'))
        self.assertRaises(akshell.LoginRequiredError,
                          akshell.AppData,
                          APP, spot_name=SPOT)
        self.assertRaises(AssertionError,
                          akshell.AppData,
                          APP, owner_name='illegal')
        self.assertRaises(AssertionError,
                          akshell.AppData,
                          APP, owner_name=USER)
        self.assertRaises(
            akshell.RequestError,
            lambda: akshell.AppData(APP).get('code', 'no_such_entry', '.'))
        _write('file', '')
        self.assertRaises(akshell.RequestError,
                          lambda: akshell.AppData(APP).put('code', '', '.'))

    def testPut(self):
        self._launch(['get', APP, '-l', 'code', '.'])
        _write('file', 'some text')
        os.mkdir('some_dir')
        shutil.rmtree('dir')
        output = self._launch(['put', APP, '-c', '-l', 'code', '.'])
        self.assert_('file' in output)
        self.assert_('some_dir' in output)
        self.assert_('dir' in output)
        os.rmdir('some_dir')
        _write('some_dir', '')
        self.assert_('some_dir' in
                     self._launch(['put', APP, '-f', '-l', 'code', '.']))

    def testEval(self):
        self.assertEqual(self._launch(['eval', APP, 'x']), '42\n')
        self._launch(['eval', APP, '-s', SPOT, 'y=1'])
        self.assertEqual(self._launch(['eval', APP, '-s', SPOT, 'y']), '1\n')
        self.assert_(self._launch(['eval', APP, 'y']).startswith('Exception'))
        

def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(CommandTestCase))
    suite.addTest(unittest.makeSuite(WorkTestCase))
    return suite


def _process_coverage():
    f, s, m, mf = coverage.analysis(akshell)
    html_file = open('coverage.html', 'wb')
    try:
        coverage_color.colorize_file(f, outstream=html_file, not_covered=mf)
    finally:
        html_file.close()

        
def main():
    collecting_coverage = False
    if '--cov' in sys.argv:
        sys.argv.remove('--cov')
        coverage.start()
        collecting_coverage = True
    global akshell
    akshell = __import__('akshell')
    try:
        unittest.main(defaultTest='suite')
    finally:
        if collecting_coverage:
            coverage.stop()
            _process_coverage()
            coverage.report(akshell, show_missing=False)
            coverage.erase()
            
    
if __name__ == '__main__':
    main()
