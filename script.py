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

from optparse import OptionParser, Option, SUPPRESS_HELP
from getpass import getpass
from urllib2 import URLError
import os.path
import sys

import akshell


HELP = '''\
Usage: akshell <command> [options] [args]
Type "akshell help <command>" for help on a specific command.

Available commands:
    login      login to the server and store credentials
    logout     logout from the server and remove the stored credentials
    get        get application code from the server
    put        put application code to the server
    eval       evaluate an expression
    help       print help for given commands or a help overview

akshell is a tool for development access to http://www.akshell.com/
'''


class CommandOptionParser(OptionParser):
    def __init__(self, *args, **kwds):
        OptionParser.__init__(self, *args, **kwds)
        help_option = self.option_list[-1]
        assert help_option.get_opt_string() == '--help'
        help_option.help = SUPPRESS_HELP
        self.add_option('--server', default=akshell.SERVER, help=SUPPRESS_HELP)
        
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
        opts, args = OptionParser.parse_args(self, args)
        akshell.SERVER = opts.server
        return opts, args

    
def help_command(args):
    if not args:
        print HELP,
        return
    if args in (['--help'], ['-h']):
        print '''\
Usage: akshell help [COMMAND...]

Print help for given commands of a help overview.'''
        return
    is_first = True
    for command in args:
        try:
            command_handler = command_handlers[command]
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
    parser = CommandOptionParser(
        usage='akshell login',
        description='Login to the server and store credentials locally.')
    parser.parse_args(args)
    try:
        name = raw_input('Name: ')
        password = getpass('Password: ')
    except EOFError:
        print
        return
    akshell.login(name, password)

    
def logout_command(args):
    parser = CommandOptionParser(
        usage='akshell logout',
        description='Logout from the server and remove the stored credentials.')
    parser.parse_args(args)
    akshell.logout()
    

def parse_app_owner_spot(string):
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


FORCE_OPTION = Option(
    '-f', '--force',
    default=False, action='store_true',
    help='Don\'t ask for confirmation of release code actions')


def _transfer_command(direction, args, command_name, descr_title):
    parser = CommandOptionParser(
        usage=('Usage: akshell %s [options] '
               'APP[:[OWNER@]SPOT][/REMOTE_PATH] [LOCAL_PATH]'
               % command_name),
        description=descr_title + '''
Unless "quiet" option is set print deleted entries (D mark),
created directories (C mark) and saved files (S mark).
LOCAL_PATH defaults to the REMOTE_PATH base name if avaliable or
the current directory otherwise.
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
                            % ':'.join(akshell.IGNORES)),
                     ))
    if direction == akshell.TO_SERVER:
        parser.add_option(FORCE_OPTION)
        parser.add_option('-e', '--expr',
                          help='''\
Evaluate EXPR after put, print a value or an exception''')
    opts, args = parser.parse_args(args)
    if not args or len(args) > 2:
        sys.stderr.write('"%s" command requires 1 or 2 arguments.\n'
                         % command_name)
        sys.exit(1)
    app_owner_spot, sep_, remote_path = args[0].partition('/')
    app_name, owner_name, spot_name = parse_app_owner_spot(app_owner_spot)
    remote_path = remote_path.strip('/')
    local_path = args[1] if len(args) > 1 else remote_path.rpartition('/')[2]
    ignores = (akshell.IGNORES if opts.ignore is None else
               [ignore for ignore in opts.ignore.split(':') if ignore])
    if (direction == akshell.TO_SERVER and
        not (spot_name or opts.force or _confirm('Put release code'))):
        return
    delete, create, save = akshell.transfer(
        direction, app_name, owner_name, spot_name,
        remote_path, local_path or '.',
        ignores, opts.clean)
    if not opts.quiet:
        for prefix, routes in (('D', delete), ('C', create), ('S', save)):
            for route in routes:
                print prefix, (os.path.join(local_path, *route)
                               if direction == akshell.FROM_SERVER else
                               '/'.join(([remote_path] if remote_path else []) +
                                        route))
    if getattr(opts, 'expr', None):
        print akshell.evaluate(app_name, spot_name, opts.expr)[1]
            

def get_command(args):
    _transfer_command(akshell.FROM_SERVER,
                      args,
                      'get',
                      'Get release or spot code from the server.')


def put_command(args):
    _transfer_command(akshell.TO_SERVER,
                      args,
                      'put',
                      'Put release or spot code to the server.')


def eval_command(args):
    parser = CommandOptionParser(
        usage='Usage: akshell eval APP[:SPOT] EXPR',
        description='''\
Evaluate EXPR in a release or spot version of an application.
Print a value or an exception occured.
''',
        option_list=(FORCE_OPTION,))
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
    print akshell.evaluate(app_name, spot_name, args[1])[1]
    

command_handlers = {'login': login_command,
                    'logout': logout_command,
                    'get': get_command,
                    'put': put_command,
                    'eval': eval_command,
                    'help': help_command,
                    }
    

def main(args=None):
    if args is None:
        args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print HELP,
        return
    if args[0] in ('-v', '--version'):
        print 'akshell', akshell.__version__
        return
    command = args[0]
    try:
        command_handler = command_handlers[command]
    except KeyError:
        sys.stderr.write('''\
Unknown command: '%s'
Type 'akshell help' for usage.
''' % command)
        sys.exit(1)
    try:
        command_handler(args[1:])
        return
    except akshell.Error, error:
        sys.stderr.write(str(error) + '\n')
    except KeyboardInterrupt:
        sys.stderr.write('\nInterrupted!\n')
    except URLError, error:
        sys.stderr.write(str(error.reason) + '\n')
    sys.exit(1)


if __name__ == '__main__': main()
