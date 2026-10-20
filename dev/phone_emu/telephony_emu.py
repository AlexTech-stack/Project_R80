"""A stand-in for PipeWire's Bluetooth telephony service (org.pipewire.Telephony), PC only.

What hu-phoned talks to on the target, as PipeWire 1.4 publishes it (spa/plugins/bluez5/
telephony.c): /org/pipewire/Telephony (ObjectManager of the audio gateways, one per
connected phone), /org/pipewire/Telephony/agN (AudioGateway1: Dial, HangupAll, SendTones,
Address; ObjectManager of its calls) and .../agN/callM (Call1: Answer, Hangup,
LineIdentification, Name, State). The phone side is driven from Python, by the BoAt tests
and the phone panel:

    tel = FakeTelephony(conn)                    # conn: a dbus-python connection with a GLib main loop
    conn.request_name("org.pipewire.Telephony")
    ag = tel.add_phone("AA:BB:CC:DD:EE:FF")      # a phone connects (hands-free)
    call = ag.ring("+4917100000", "Anna")        # it rings at the HU
    call.set_state("active")                     # ... the far end answers an outgoing call
    call.end()                                   # ... someone hangs up on the phone side
    tel.remove_phone(ag)                         # the phone goes away
    ag.dialled, ag.tones                         # what the HU asked for
"""
from __future__ import annotations

import dbus
import dbus.service

TEL, ROOT = "org.pipewire.Telephony", "/org/pipewire/Telephony"
AG_IFACE, TRANSPORT_IFACE, CALL_IFACE = TEL + ".AudioGateway1", TEL + ".AudioGatewayTransport1", TEL + ".Call1"
OM, PROPS = "org.freedesktop.DBus.ObjectManager", "org.freedesktop.DBus.Properties"
ERR = TEL + ".Error."


class Call(dbus.service.Object):
    def __init__(self, ag: "Gateway", n: int, number: str, name: str, state: str):
        self.ag, self.path = ag, f"{ag.path}/call{n}"
        super().__init__(ag.conn, self.path)
        self.props = {"LineIdentification": number, "IncomingLine": "", "Name": name, "Multiparty": False, "State": state}

    def ifaces(self):
        return {CALL_IFACE: dbus.Dictionary({k: (dbus.Boolean(v) if isinstance(v, bool) else dbus.String(v))
                                             for k, v in self.props.items()}, signature="sv")}

    def set_state(self, state: str):
        """The phone side: e.g. the far end answered ("active") or put us on hold."""
        self.props["State"] = state
        self.PropertiesChanged(CALL_IFACE, dbus.Dictionary({"State": state}, signature="sv"), dbus.Array([], signature="s"))

    def end(self):
        """The call is over (hung up on either side): disconnected, then gone, as PipeWire does it."""
        if self.path not in self.ag.calls:
            return
        self.set_state("disconnected")
        del self.ag.calls[self.path]
        self.ag.InterfacesRemoved(dbus.ObjectPath(self.path), dbus.Array([CALL_IFACE], signature="s"))
        self.remove_from_connection()

    @dbus.service.method(CALL_IFACE)
    def Answer(self):
        if self.props["State"] not in ("incoming", "waiting"):
            raise dbus.exceptions.DBusException("call is not ringing", name=ERR + "InvalidState")
        self.ag.answered.append(self.path)
        self.set_state("active")

    @dbus.service.method(CALL_IFACE)
    def Hangup(self):
        self.ag.hung_up.append(self.path)
        self.end()

    @dbus.service.method(PROPS, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        return self.ifaces()[CALL_IFACE][str(name)]

    @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return self.ifaces()[CALL_IFACE]

    @dbus.service.signal(PROPS, signature="sa{sv}as")
    def PropertiesChanged(self, iface, changed, invalidated):
        pass


class Gateway(dbus.service.Object):
    def __init__(self, tel: "FakeTelephony", n: int, address: str):
        self.tel, self.conn, self.path, self.address = tel, tel.conn, f"{ROOT}/ag{n}", address
        super().__init__(tel.conn, self.path)
        self.calls: dict[str, Call] = {}
        self.count = 0
        self.dialled, self.tones, self.answered, self.hung_up = [], [], [], []
        self.fail_dial = None                  # set to an error name to make Dial fail like a phone would

    def ifaces(self):
        return {AG_IFACE: dbus.Dictionary({"Address": self.address}, signature="sv"),
                TRANSPORT_IFACE: dbus.Dictionary({"State": "idle", "Codec": dbus.Byte(1), "RejectSCO": False}, signature="sv")}

    def add_call(self, number: str, name: str, state: str) -> Call:
        self.count += 1
        call = Call(self, self.count, number, name, state)
        self.calls[call.path] = call
        self.InterfacesAdded(dbus.ObjectPath(call.path), call.ifaces())
        return call

    def ring(self, number: str, name: str = "") -> Call:
        """The phone side: a call comes in."""
        return self.add_call(number, name, "incoming")

    @dbus.service.method(AG_IFACE, in_signature="s", out_signature="o")
    def Dial(self, number):
        if self.fail_dial:
            raise dbus.exceptions.DBusException("the phone refused", name=ERR + self.fail_dial)
        self.dialled.append(str(number))
        return dbus.ObjectPath(self.add_call(str(number), "", "dialing").path)

    @dbus.service.method(AG_IFACE)
    def HangupAll(self):
        for call in list(self.calls.values()):
            call.end()

    @dbus.service.method(AG_IFACE, in_signature="s")
    def SendTones(self, tones):
        self.tones.append(str(tones))

    @dbus.service.method(OM, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        return dbus.Dictionary({dbus.ObjectPath(p): c.ifaces() for p, c in self.calls.items()}, signature="oa{sa{sv}}")

    @dbus.service.signal(OM, signature="oa{sa{sv}}")
    def InterfacesAdded(self, path, ifaces):
        pass

    @dbus.service.signal(OM, signature="oas")
    def InterfacesRemoved(self, path, ifaces):
        pass


class FakeTelephony(dbus.service.Object):
    def __init__(self, conn):
        super().__init__(conn, ROOT)
        self.conn = conn
        self.gateways: dict[str, Gateway] = {}
        self.count = 0

    def add_phone(self, address: str) -> Gateway:
        self.count += 1
        ag = Gateway(self, self.count, address)
        self.gateways[ag.path] = ag
        self.InterfacesAdded(dbus.ObjectPath(ag.path), ag.ifaces())
        return ag

    def remove_phone(self, ag: Gateway):
        for call in list(ag.calls.values()):
            call.end()
        self.gateways.pop(ag.path, None)
        self.InterfacesRemoved(dbus.ObjectPath(ag.path), dbus.Array([AG_IFACE, TRANSPORT_IFACE], signature="s"))
        ag.remove_from_connection()

    @dbus.service.method(OM, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        return dbus.Dictionary({dbus.ObjectPath(p): ag.ifaces() for p, ag in self.gateways.items()}, signature="oa{sa{sv}}")

    @dbus.service.signal(OM, signature="oa{sa{sv}}")
    def InterfacesAdded(self, path, ifaces):
        pass

    @dbus.service.signal(OM, signature="oas")
    def InterfacesRemoved(self, path, ifaces):
        pass
