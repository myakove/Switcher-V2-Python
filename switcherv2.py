import socket
import binascii as ba
import time
import struct
import socket
import sys
import os
import datetime
import re
import signal

ON_OFF_DATA = "000000000000000000000000000000000000000000000000000000000106000"
AUTO_CLOSE_DATA = "00000000000000000000000000000000000000000000000000000000040400"


class Switcherv2:
    def __init__(self):
        self.connection = None
        self.ip = "192.168.10.10"
        self.session = "00000000"
        self.current_session = None
        self.p_key = b"00000000000000000000000000000000"
        self.phone_id = "a71e"
        self.device_pass = "34363733"
        self.device_id = "09c01e"
        self.upd_ip = "0.0.0.0"
        self.udp_port = 20002
        self.state_on = "0100"
        self.state_off = "0000"
        if not self.current_session:
            self.connect()
            self.login()

    @staticmethod
    def hour_match(hour):
        match = re.compile(r"^([0-9]|0[0-9]|1[0-9]|2[0-3]):[0-5][0-9]$")
        return match.match(hour)

    @property
    def _device_data(self):
        return (
            "fef05d0002320102"
            f"{self.current_session}"
            "340001000000000000000000"
            f"{self.get_ts}"
            "00000000000000000000f0fe"
            f"{self.device_id}"
            "00"
            f"{self.phone_id}"
            "0000"
            f"{self.device_pass}"
        )

    @staticmethod
    def binascii_to_str(data):
        return ba.hexlify(data).decode("utf-8")

    @property
    def get_ts(self):
        return self.binascii_to_str(data=struct.pack("<I", int(round(time.time()))))

    def crc_sign_full_packet_com_key(self, p_data):
        crc = self.binascii_to_str(
            data=struct.pack(">I", ba.crc_hqx(ba.unhexlify(p_data), 0x1021))
        )
        p_data = p_data + crc[6:8] + crc[4:6]
        crc = crc[6:8] + crc[4:6] + self.binascii_to_str(data=self.p_key)
        crc = self.binascii_to_str(
            data=struct.pack(">I", ba.crc_hqx(ba.unhexlify(crc), 0x1021))
        )
        p_data = p_data + crc[6:8] + crc[4:6]
        return p_data

    def connect(self):
        self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connection.connect((self.ip, 9957))

    def login(self):
        data = (
            "fef052000232a100"
            f"{self.session}"
            "340001000000000000000000"
            f"{self.get_ts}"
            "00000000000000000000f0fe1c00"
            f"{self.phone_id}"
            "0000"
            f"{self.device_pass}"
            "00000000000000000000000000000000000000000000000000000000"
        )
        data = self.crc_sign_full_packet_com_key(p_data=data)
        print("Sending Login Packet to Switcher...")
        self.connection.send(ba.unhexlify(data))
        res = self.connection.recv(1024)
        self.current_session = self.binascii_to_str(data=res)[16:24]
        if not self.current_session:
            self.connection.close()
            print(
                "Operation failed, Could not acquire SessionID, Please try again..."
            )

        else:
            print(f"Received SessionID: {self.current_session}")

    def get_response(self, data):
        data = self.crc_sign_full_packet_com_key(p_data=data)
        self.connection.send(ba.unhexlify(data))
        return self.connection.recv(1024)

    @property
    def get_data(self):
        data = (
            "fef0300002320103"
            f"{self.current_session}"
            "340001000000000000000000"
            f"{self.get_ts}"
            "00000000000000000000f0fe"
            f"{self.device_id}"
            "00"
        )
        print("Getting Switcher V2 data...")
        time.sleep(3)
        return self.get_response(data=data)

    @property
    def name(self):
        return self.binascii_to_str(data=self.get_data)[40:60]

    @property
    def state(self):
        return self.binascii_to_str(data=self.get_data)[150:154]

    @property
    def power(self):
        bin_out = ba.hexlify(self.get_data)[154:162]
        return int(bin_out[2:4] + bin_out[0:2], 16)

    @property
    def electric_power(self):
        return f"{(self.power / float(220))}(A)"

    @property
    def power_consumption(self):
        return f"{str(self.power)}(W)"

    def power_on(self, duration=None):
        duration_action = ON_OFF_DATA
        if duration:
            duration_action += f"100{self._prepare_timer(minutes=duration)}"
            if not 0 < duration <= 60:
                print("Enter a value between 1-60 minutes")
                return

        if self.state == self.state_on:
            if not duration:
                print("Device is already ON")
                return

        print(f"Sending ON {duration if duration else ''} Command to Switcher...")
        return self.send_action(action=f"{ON_OFF_DATA}10000000000" if not duration else duration_action)

    def power_off(self):
        if self.state == self.state_off:
            print("Device is already OFF")
            return

        print("Sending OFF Command to Switcher...")
        return self.send_action(action=f"{ON_OFF_DATA}00000000000")

    @property
    def auto_shutdown_countdown(self):
        bin_out = ba.hexlify(self.get_data)[178:186]
        open_time = int(bin_out[6:8] + bin_out[4:6] + bin_out[2:4] + bin_out[0:2], 16)
        m_, s_ = divmod(open_time, 60)
        h_, m_ = divmod(m_, 60)
        return "%d:%02d:%02d" % (h_, m_, s_)

    def send_action(self, action):
        data = self._device_data
        data += f"{action}"
        return self.get_response(data=data)

    def _prepare_timer(self, minutes):
        s_seconds = int(minutes) * 60
        s_delay = struct.pack("<I", s_seconds)
        return self.binascii_to_str(data=s_delay)

    def auto_close(self, hour):
        if not self.hour_match(hour=hour):
            print("Please enter a value between 01:00 - 23:59")
            return

        return self.send_action(
            action=f"{AUTO_CLOSE_DATA}{self._set_auto_close(hours=hour)}"
        )

    @staticmethod
    def _set_auto_close(hours):
        hour, minutes = hours.split(":")
        m_seconds = int(hour) * 3600 + int(minutes) * 60
        if m_seconds < 3600:
            print("Value Can't be less than 1 hour!")
            return

        elif m_seconds > 86340:
            print("Value can't be more than 23 hours and 59 minutes!")
            return

        print(f"Auto shutdown was set to {hours} Hour(s)")
        return ba.hexlify(struct.pack("<I", m_seconds)).decode("utf-8")


if __name__ == "__main__":
    sw = Switcherv2()
    sw.power_on()
    # sw.auto_close(hour="01:00")
    sw.power_off()
    # sw.power_on(30)
    # sw.power_off
    # sw.power_on
    # print(sw.name)
    # sw.power_on
    # import ipdb;ipdb.set_trace()
