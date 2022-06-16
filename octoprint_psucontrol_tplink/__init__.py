# coding=utf-8
from __future__ import absolute_import

__author__ = "Shawn Bruce <kantlivelong@gmail.com>"
__license__ = "GNU Affero General Public License http://www.gnu.org/licenses/agpl.html"
__copyright__ = "Copyright (C) 2021 Shawn Bruce - Released under terms of the AGPLv3 License"

import octoprint.plugin
import socket
import json
from struct import unpack
from builtins import bytes
import struct

class PSUControl_TPLink(octoprint.plugin.StartupPlugin,
                        octoprint.plugin.RestartNeedingPlugin,
                        octoprint.plugin.TemplatePlugin,
                        octoprint.plugin.SettingsPlugin):

    def __init__(self):
        self.config = dict()


    def get_settings_defaults(self):
        return dict(
            address = '',
            plug = 0,

            lightEnabled = False,
            lightAddress = '',
            lightPlug = 0,

            otherEnabled = False,
            otherAddress = '',
            otherPlug = 0
        )


    def on_settings_initialized(self):
        self.reload_settings()


    def reload_settings(self):
        for k, v in self.get_settings_defaults().items():
            if type(v) == str:
                v = self._settings.get([k])
            elif type(v) == int:
                v = self._settings.get_int([k])
            elif type(v) == float:
                v = self._settings.get_float([k])
            elif type(v) == bool:
                v = self._settings.get_boolean([k])

            self.config[k] = v
            self._logger.debug("{}: {}".format(k, v))


    def on_startup(self, host, port):
        psucontrol_helpers = self._plugin_manager.get_helpers("psucontrol")
        if not psucontrol_helpers or 'register_plugin' not in psucontrol_helpers.keys():
            self._logger.warning("The version of PSUControl that is installed does not support plugin registration.")
            return

        self._logger.debug("Registering plugin with PSUControl")
        psucontrol_helpers['register_plugin'](self)


    def get_sysinfo(self, host):
        cmd = dict(system=dict(get_sysinfo=dict()))
        result = self.send(cmd, host)

        try:           
            return result['system']['get_sysinfo']
        except (TypeError, KeyError):
            self._logger.error("Expecting get_sysinfo, got result={}".format(result))
            return dict()


    def turn_psu_on(self):
        self._logger.debug("Switching PSU On")
        self.turn_on_plug(self.config['address'], self.config['plug'])

        if self.config['lightEnabled']:
            self.turn_light_on()

        if self.config['otherEnabled']:
            self.turn_other_on()


    def turn_psu_off(self):
        self._logger.debug("Switching PSU Off")
        self._logger.debug(f"{self.config}")
        self.turn_off_plug(self.config['address'], self.config['plug'])

        if self.config['lightEnabled']:
            self.turn_light_off()

        if self.config['otherEnabled']:
            self.turn_other_off()


    def get_psu_state(self):
        self._logger.debug("get_psu_state")
        return self.get_plug_state(self.config['address'], self.config['plug'])


    def turn_light_on(self):
        self._logger.debug("Switching Light On")
        self.turn_on_plug(self.config['lightAddress'], self.config['lightPlug'])


    def turn_light_off(self):
        self._logger.debug("Switching Light Off")
        self.turn_off_plug(self.config['lightAddress'], self.config['lightPlug'])


    def get_light_state(self):
        self._logger.debug("get_light_state")
        return self.get_plug_state(self.config['lightAddress'], self.config['lightPlug'])

    def turn_other_on(self):
        self._logger.debug("Switching Other On")
        self.turn_on_plug(self.config['otherAddress'], self.config['otherPlug'])


    def turn_other_off(self):
        self._logger.debug("Switching Other Off")
        self.turn_off_plug(self.config['otherAddress'], self.config['otherPlug'])


    def get_other_state(self):
        self._logger.debug("get_other_state")
        return self.get_plug_state(self.config['otherAddress'], self.config['otherPlug'])



    def encrypt(self, string):
        key = 171
        result = b"\0\0\0" + bytes([len(string)])
        for i in bytes(string.encode('latin-1')):
            a = key ^ i
            key = a
            result += bytes([a])
        return result


    def decrypt(self, string):
        key = 171
        result = b""
        for i in bytes(string):
            a = key ^ i
            key = i
            result += bytes([a])
        return result.decode('latin-1')

    def get_plug_state(self, host, plug):
        self._logger.debug("get_plug_state")
        sysinfo = self.get_sysinfo(host)

        if not sysinfo:
            return False

        result = False

        if plug > 0:
            try:
                result = bool(sysinfo['children'][plug - 1]['state'])
            except KeyError:
                self._logger.error(
                    "Expecting state for child index {}, got sysinfo={}".format(plug - 1, sysinfo))
        else:
            try:
                result = bool(sysinfo['relay_state'])
            except KeyError:
                self._logger.error("Expecting relay_state, got sysinfo={}".format(sysinfo))

        return result

    def set_plug_state(self, state, host, plug):
        cmd = dict(system=dict(set_relay_state=dict(state=state)))
        self.send_to_plug(cmd, host, plug)


    def turn_on_plug(self, host, plug):
        self._logger.debug("turn_on_plug")
        self.set_plug_state(1, host, plug)


    def turn_off_plug(self, host, plug):
        self._logger.debug("turn_off_plug")
        self.set_plug_state(0, host, plug)

    def send_to_plug(self, cmd, host, plug):
        if plug > 0:
            sysinfo = self.get_sysinfo(host)

            if not sysinfo:
                return dict()

            try:
                device_id = sysinfo['children'][plug - 1]['id']
            except KeyError:
                self._logger.error(
                    "Expecting id for child index {}, got sysinfo={}".format(plug - 1, sysinfo))
                return dict()

            cmd.update(dict(context=dict(child_ids=[device_id])))

        self.send(cmd, host)

    def send(self, cmd, host):
        self._logger.debug("send={}".format(cmd))
        cmd_json = json.dumps(cmd)

        result = dict()

        try:
            host = socket.gethostbyname(host)
        except Exception:
            self._logger.error("Unable to resolve hostname {}".format(host))
            return result

        port = 9999

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect((host, port))
        except (OSError, ConnectionRefusedError) as e:
            self._logger.error("Unable to connect to {}:{} - {}".format(host, port, e.strerror))
            return result

        try:
            s.send(self.encrypt(cmd_json))
        except socket.error as e:
            self._logger.error("Error sending data - {}".format(e.strerror))
            return result

        try:
            data = s.recv(1024)
            len_data = unpack('>I', data[0:4])
            while (len(data) - 4) < len_data[0]:
                data = data + s.recv(1024)
        except socket.timeout as e:
            self._logger.error("Error receiving data - {}".format(e))
            return result
        except struct.error:
            self._logger.error("Error invalid data received")
            return result

        s.close()

        result = json.loads(self.decrypt(data[4:]))
        self._logger.debug("recv={}".format(result))

        return result

    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        self.reload_settings()


    def get_settings_version(self):
        return 1


    def on_settings_migrate(self, target, current=None):
        pass


    def get_template_configs(self):
        return [
            dict(type="settings", custom_bindings=False)
        ]


    def get_update_information(self):
        return dict(
            psucontrol_tplink=dict(
                displayName="PSU Control - TPLink",
                displayVersion=self._plugin_version,

                # version check: github repository
                type="github_release",
                user="kantlivelong",
                repo="OctoPrint-PSUControl-TPLink",
                current=self._plugin_version,

                # update method: pip w/ dependency links
                pip="https://github.com/kantlivelong/OctoPrint-PSUControl-TPLink/archive/{target_version}.zip"
            )
        )

__plugin_name__ = "PSU Control - TPLink"
__plugin_pythoncompat__ = ">=2.7,<4"

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = PSUControl_TPLink()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    }
