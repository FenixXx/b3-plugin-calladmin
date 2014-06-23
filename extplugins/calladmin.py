#
# Calladmin Plugin for BigBrotherBot(B3) (www.bigbrotherbot.net)
# Copyright (C) 2013 Daniele Pantaleone <fenix@bigbrotherbot.net>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA
#
# CHANGELOG
#
#   13/02/2014 - 1.0 - Fenix
#   - initial version
#   13/04/2014 - 1.1 - Fenix
#   - changed default arguments of 'command' method to be None objects
#   - added backwards compatibility with B3 version < 1.10dev
#   23/06/2014 - 1.2 - Fenix
#   - rewritten plugin from scratch

__author__ = 'Fenix'
__version__ = '1.2'

import b3
import b3.plugin
import b3.events
import telnetlib
import thread
import time
import re

from ConfigParser import NoOptionError

try:
    # import the getCmd function
    import b3.functions.getCmd as getCmd
except ImportError:
    # keep backward compatibility
    def getCmd(instance, cmd):
        cmd = 'cmd_%s' % cmd
        if hasattr(instance, cmd):
            func = getattr(instance, cmd)
            return func
        return None

class CalladminPlugin(b3.plugin.Plugin):

    adminPlugin = None
    adminRequest = None

    patterns = {
        'p1': '[B][ADMIN REQUEST][/B] [B]%s [%s][/B] connected to [B]%s[/B]',
        'p2': '[B][ADMIN REQUEST][/B] [B]%s[/B] disconnected from [B]%s[/B]',
        'p3': '[B][ADMIN REQUEST][/B] [B]%s[/B] requested an admin on [B]%s[/B] : [B]%s[/B]',
    }

    settings = {
        'ip': '127.0.0.1',
        'port': 10011,
        'serverid': 1,
        'username': '',
        'password': '',
        'hostname': '',
        'treshold': 3600,
    }

    ####################################################################################################################
    ##                                                                                                                ##
    ##   STARTUP                                                                                                      ##
    ##                                                                                                                ##
    ####################################################################################################################

    def __init__(self, console, config=None):
        """
        Build the plugin object
        """
        b3.plugin.Plugin.__init__(self, console, config)
        self.adminPlugin = self.console.getPlugin('admin')
        if not self.adminPlugin:
            self.critical('could not start without admin plugin')
            raise SystemExit(220)

    def onLoadConfig(self):
        """
        Load plugin configuration
        """
        try:
            self.settings['treshold'] = self.config.getint('teamspeak', 'treshold')
            self.debug('loaded settings/treshold: %s' % self.settings['treshold'])
        except NoOptionError:
            self.warning('could not find settings/treshold in config file, using default: %s' % self.settings['treshold'])
        except ValueError, e:
            self.error('could not load settings/treshold config value: %s' % e)
            self.debug('using default value (%s) for settings/treshold' % self.settings['treshold'])

        try:
            self.settings['ip'] = self.config.get('teamspeak', 'ip')
            self.debug('loaded teamspeak/ip: %s' % self.settings['ip'])
        except NoOptionError:
            self.warning('could not find teamspeak/ip in config file, using default: %s' % self.settings['ip'])

        try:
            self.settings['port'] = self.config.getint('teamspeak', 'port')
            self.debug('loaded teamspeak/port: %s' % self.settings['port'])
        except NoOptionError:
            self.warning('could not find teamspeak/port in config file, using default: %s' % self.settings['port'])
        except ValueError, e:
            self.error('could not load teamspeak/port config value: %s' % e)
            self.debug('using default value (%s) for teamspeak/port' % self.settings['port'])

        try:
            self.settings['serverid'] = self.config.getint('teamspeak', 'serverid')
            self.debug('loaded teamspeak/serverid: %s' % self.settings['serverid'])
        except NoOptionError:
            self.warning('could not find teamspeak/serverid in config file, '
                         'using default: %s' % self.settings['serverid'])
        except ValueError, e:
            self.error('could not load teamspeak/serverid config value: %s' % e)
            self.debug('using default value (%s) for teamspeak/serverid' % self.settings['serverid'])

        try:
            self.settings['username'] = self.config.get('teamspeak', 'username')
            self.debug('loaded teamspeak/username: %s' % self.settings['username'])
        except NoOptionError:
            self.error('could not find teamspeak/username in config file: plugin will be disabled')

        try:
            self.settings['password'] = self.config.get('teamspeak', 'password')
            self.debug('loaded teamspeak/password: %s' % self.settings['password'])
        except NoOptionError:
            self.error('could not find teamspeak/password in config file: plugin will be disabled')

        # get the server hostname
        hostname = self.console.getCvar('sv_hostname').getString()
        self.settings['hostname'] = self.console.stripColors(hostname)

        # check for login credentials being specified in config file
        if not self.settings['username'] or not self.settings['password']:
            self.warning('invalid plugin configuration: disabling the plugin')
            self.disable()

    def onStartup(self):
        """
        Initialize plugin settings
        """
        # register our commands
        if 'commands' in self.config.sections():
            for cmd in self.config.options('commands'):
                level = self.config.get('commands', cmd)
                sp = cmd.split('-')
                alias = None
                if len(sp) == 2:
                    cmd, alias = sp

                func = getCmd(self, cmd)
                if func:
                    self.adminPlugin.registerCommand(self, cmd, level, func, alias)

        try:
            # B3 > 1.10dev
            self.registerEvent(self.console.getEventID('EVT_CLIENT_CONNECT'), self.onConnect)
            self.registerEvent(self.console.getEventID('EVT_CLIENT_DISCONNECT'), self.onDisconnect)
        except TypeError:
            # B3 < 1.10dev
            self.registerEvent(self.console.getEventID('EVT_CLIENT_CONNECT'))
            self.registerEvent(self.console.getEventID('EVT_CLIENT_DISCONNECT'))

        # notice plugin startup
        self.debug('plugin started')

    ####################################################################################################################
    ##                                                                                                                ##
    ##   EVENTS                                                                                                       ##
    ##                                                                                                                ##
    ####################################################################################################################

    def onEvent(self, event):
        """
        Dispatch events
        """
        if event.type == self.console.getEventID('EVT_CLIENT_CONNECT'):
            self.onConnect(event)
        elif event.type == self.console.getEventID('EVT_CLIENT_DISCONNECT'):
            self.onDisconnect(event)

    def onConnect(self, event):
        """
        Executed when EVT_CLIENT_CONNECT is intercepted
        """
        client = event.client
        if self.adminRequest is not None:
            if client.maxLevel >= self.adminPlugin._admins_level:
                # send a message on teamspeak informing that someone connected to handle the request
                self.debug('admin connected to the server: %s [%s]' % (client.name, client.maxLevel))
                self.send_teamspeak_message(self.patterns['p1'] % (client.name, client.maxLevel, self.settings['hostname']))
                self.adminRequest['client'].message('^7[^2ADMIN ONLINE^7] %s [^3%s^7]' % (client.name, client.maxLevel))
                self.adminRequest = None

    def onDisconnect(self, event):
        """
        Executed when EVT_CLIENT_DISCONNECT is intercepted
        """
        client = event.client
        if self.adminRequest is not None:
            if self.adminRequest['client'] == client:
                self.debug('admin request canceled: %s disconnected from the server' % client.name)
                self.send_teamspeak_message(self.patterns['p2'] % (client.name, self.settings['hostname']))
                self.adminRequest = None

    def onEnable(self):
        """
        Executed when the plugin is enabled
        """
        # check for login credentials being specified in config file
        if not self.settings['username'] or not self.settings['password']:
            self.warning('invalid plugin configuration: disabling the plugin')
            self.disable()

    ####################################################################################################################
    ##                                                                                                                ##
    ##   FUNCTIONS                                                                                                    ##
    ##                                                                                                                ##
    ####################################################################################################################

    @staticmethod
    def get_time_string(s):
        """
        Return a time string given it's value in seconds
        """
        if s < 60:
            return '%d second%s' % (s, 's' if s != 1 else '')
        if 60 <= s < 3600:
            s = round(s/60)
            return '%d minute%s' % (s, 's' if s != 1 else '')
        s = round(s/3600)
        return '%d hour%s' % (s, 's' if s != 1 else '')

    def send_teamspeak_message(self, message):
        """
        Send the admin request on the Teamspeak 3 server
        """
        try:

            d1 = {'client_login_name': self.settings['username'], 'client_login_password': self.settings['password']}
            d2 = {'sid': self.settings['serverid']}
            d3 = {'targetmode': 3, 'target': 1, 'msg': message}

            # print in the log what we are going to send
            self.debug('broadcasting admin request: %s' % message)

            # establish a connection object with the teamspeak server query
            sq = ServerQuery(self.settings['ip'], self.settings['port'])
            sq.connect()
            sq.command('login', d1)
            sq.command('use', d2)
            sq.command('sendtextmessage', d3)

            return True

        except (TS3Error, telnetlib.socket.error), e:
            self.error('could not broadcast message over the teamspeak 3 server query interface: %s' % e)
            if e.code == 3329:
                self.warning('B3 is banned from the Teamspeak 3 server: make sure you add the b3 '
                             'ip to your Teamspeak 3 server white list (query_ip_whitelist.txt)')
            return False

    ####################################################################################################################
    ##                                                                                                                ##
    ##   COMMANDS                                                                                                     ##
    ##                                                                                                                ##
    ####################################################################################################################

    def cmd_calladmin(self, data, client, cmd=None):
        """
        <reason> - send an admin request
        """
        if not data:
            client.message('^7missing data, try ^3!^7help calladmin')
            return

        # checking if there are already admins online
        admins = self.adminPlugin.getAdmins()
        if len(admins) > 0:
            _list = []
            for a in admins:
                _list.append('^7%s ^7[^3%s^7]' % (a.name, a.maxLevel))
            cmd.sayLoudOrPM(client, '^7Admin%s already online: %s' % ('s' if len(_list) != 1 else '', ', '.join(_list)))
            return

        # checking if someone already submitted a request
        if self.adminRequest is not None:
            # if the previous admin request was done less than
            # self.settings['treshold'] seconds ago, block here
            when = int(time.time()) - self.adminRequest['time']
            if when < self.settings['treshold']:
                cmd.sayLoudOrPM(client, '^7Admin request ^1aborted^7: already sent ^3%s ^7ago' % self.get_time_string(when))
                return

        # send the admin request
        r = self.console.stripColors(data)
        m = self.patterns['p3'] % (client.name, self.settings['hostname'], r)

        if self.send_teamspeak_message(m):
            self.adminRequest = { 'client': client, 'reason': r, 'time': int(time.time()) }
            client.message('^7Admin request ^2sent^7: an admin will connect as soon as possible')
        else:
            self.adminRequest = None
            client.message('^7Admin request ^1failed^7: try again in few minutes')

########################################################################################################################
##                                                                                                                    ##
##  TEAMSPEAK SERVER QUERY INTERFACE                                                                                  ##
##                                                                                                                    ##
########################################################################################################################

# Copyright (c) 2009 Christoph Heer (Christoph.Heer@googlemail.com)
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.


class TS3Error(Exception):
    msg = None
    msg2 = None
    code = None
    
    def __init__(self, code, msg, msg2=None):
        """
        Object constructor
        """
        self.code = code
        self.msg = msg
        self.msg2 = msg2

    def __str__(self):
        """
        Object string representation
        """
        return "ID %s (%s) %s" % (self.code, self.msg, self.msg2)


class ServerQuery():

    _ip = None
    _query = None
    _timeout = None
    _telnet = None

    _tsregex = re.compile(r"(\w+)=(.*?)(\s|$|\|)")
    _lock = thread.allocate_lock()

    def __init__(self, ip='127.0.0.1', query=10011):
        """
        Object constructor
        """
        self._ip = ip
        self._query = int(query)
        self._timeout = 5.0

    def connect(self):
        """
        Open a link to the Teamspeak 3 query port
        """
        try:
            self._telnet = telnetlib.Telnet(self._ip, self._query)
        except telnetlib.socket.error, e:
            raise TS3Error(10, 'could not connect to the teamspeak 3 server query', e)

        output = self._telnet.read_until('TS3', self._timeout)
        if not output.endswith('TS3'):
            raise TS3Error(20, 'this is not a teamspeak 3 server query interface')

        return True

    def disconnect(self):
        """
        Close the link to the Teamspeak 3 query port
        """
        if self._telnet is not None:
            self._telnet.write('quit \n')
            self._telnet.close()
        return True

    @staticmethod
    def escaping2string(string):
        """
        Convert the escaping string form the TS3 Query to a human string
        """
        string = str(string)
        string = string.replace('\/', '/')
        string = string.replace('\s', ' ')
        string = string.replace('\p', '|')
        string = string.replace('\n', '')
        string = string.replace('\r', '')
        try:
            string = int(string)
            return string
        except ValueError:
            ustring = unicode(string, "utf-8")
            return ustring

    @staticmethod
    def string2escaping(string):
        """
        Convert a human string to a TS3 Query escaping string
        """
        if type(string) == type(int()):
            string = str(string)
        else:
            string = string.encode("utf-8")
            string = string.replace('/', '\\/')
            string = string.replace(' ', '\\s')
            string = string.replace('|', '\\p')
        return string

    def command(self, cmd, parameter=None, option=None):
        """
        Send a command with parameters and options to the TS3 Query
        """
        if parameter is None:
            parameter = {}

        if option is None:
            option = []

        telnet_cmd = cmd
        for key in parameter:
            telnet_cmd += " %s=%s" % (key, self.string2escaping(parameter[key]))
        for i in option:
            telnet_cmd += " -%s" % i
            
        telnet_cmd += '\n'
        self._lock.acquire()
        
        try:
            self._telnet.write(telnet_cmd)
            telnet_response = self._telnet.read_until("msg=ok", self._timeout)
        finally:
            self._lock.release()
        
        telnet_response = telnet_response.split(r'error id=')
        
        try:
            not_parsed_cmd_status = "id=" + telnet_response[1]
        except IndexError:
            raise TS3Error(12, "bad TS3 response : %r" % telnet_response)
        
        notparsed_info = telnet_response[0].split('|')

        if cmd.endswith("list") or len(notparsed_info) > 1:
            return_info = []
            for notparsed_infoLine in notparsed_info:
                parsed_info = self._tsregex.findall(notparsed_infoLine)
                parsed_info_dict = dict()
                for parsed_infoKey in parsed_info:
                    parsed_info_dict[parsed_infoKey[0]] = self.escaping2string(parsed_infoKey[1])
                return_info.append(parsed_info_dict)
        else:
            return_info = dict()
            parsed_info = self._tsregex.findall(notparsed_info[0])
            for parsed_infoKey in parsed_info:
                return_info[parsed_infoKey[0]] = self.escaping2string(parsed_infoKey[1])

        return_cmd_status = {}
        parsed_cmd_status = self._tsregex.findall(not_parsed_cmd_status)
        for parsed_cmd_statusLine in parsed_cmd_status:
            return_cmd_status[parsed_cmd_statusLine[0]] = self.escaping2string(parsed_cmd_statusLine[1])

        if return_cmd_status['id'] != 0:
            raise TS3Error(return_cmd_status['id'], return_cmd_status['msg'], return_cmd_status)

        return return_info
