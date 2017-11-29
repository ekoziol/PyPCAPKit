#!/usr/bin/python3
# -*- coding: utf-8 -*-


import re
import io
import textwrap


# Extractor for PCAP files
# Extract parametres from a PCAP file


from .exceptions import FormatError
from .frame import Frame
from .header import Header
from .protocol import Info


FILE = re.compile(r'''
    \A(.+?)[.](?P<exts>.*)\Z
''', re.VERBOSE | re.IGNORECASE)


class Extractor:
    """Extractor for PCAP files.

    Properties:
        _frame -- int, frame number
        _ofile -- object, temperory output writer

        _dlink -- str, data link layer protocol
        _netwk -- str, network layer protocol
        _trans -- str, transport layer protocol
        _applc -- str, application layer protocol

        _frame -- list, each item contains `Info` of a record/package
            |--> gbhdr -- Info object, global header
            |--> frame 1 -- Info object, record/package header
            |       |--> dlink -- Info object, link layer header
            |       |--> netwk -- Info object, internet layer header
            |       |--> trans -- Info object, transport layer header
            |       |--> applc -- Info object, application layer datagram
            |--> frame 2 -- Info object, record/package header
            |       |--> ......

    Usage:
        reader = Analyer(fmt='plist', fin='in', fout='out')

    """

    ##########################################################################
    # Properties.
    ##########################################################################

    @property
    def info(self):
        return self._frame

    @property
    def length(self):
        return self._frnum

    ##########################################################################
    # Data modules.
    ##########################################################################

    # Not hashable
    __hash__ = None

    def __init__(self, *, fmt=None, fin=None, fout=None, auto=True):
        """Initialise PCAP Reader.

        Keyword arguemnts:
            fmt  -- str, file format of output
                    <keyword> 'plist' / 'json' / 'tree' / 'html'
            fin  -- str, file name to be read; if file not exist, raise error
            fout -- str, file name to be written

        """
        fmt_none = (fmt is None)

        if fin is None:
            ifnm = 'in.pcap'
        else:
            ifnm = fin if '.pcap' in fin else '{fin}.pcap'.format(fin=fin)

        if fout is None:
            if fmt_none:
                raise FormatError('Output format unspecified.')
            else:
                ofnm = 'out.{fmt}'.format(fmt=fmt)
        else:
            ofmt = FILE.match(fout)
            if ofmt is None:
                if fmt_none:
                    raise FormatError('Output format unspecified.')
                else:
                    ofnm = '{out}.{fmt}'.format(out=fout, fmt=fmt)
            else:
                ofnm = fout
                fmt = ofmt.group('exts')

        if fmt == 'plist':
            from .jsformat.plist import PLIST as output     # output PLIST file
        elif fmt == 'json':
            from .jsformat.json import JSON as output       # output JSON file
        elif fmt == 'tree':
            from .jsformat.tree import Tree as output       # output treeview text file
        elif fmt == 'html':
            from .jsformat.html import JavaScript as output # output JavaScript file
            fmt = 'js'
        elif fmt == 'xml':
            from .jsformat.xml import XML as output         # output XML file
        else:
            raise FormatError('Unsupported output format: {}'.format(fmt))

        self._frnum = 1                     # frame number
        self._frame = []                    # frame record
        self._ofile = output(ofnm)          # output file

        self._ifile = open(ifnm, 'rb')
        self.record_header()         # read PCAP global header
        self.record_frames(auto)     # read frames

    ##########################################################################
    # Utilities.
    ##########################################################################

    def record_header(self):
        """Read global header.

        - Extract global header.
        - Make Info object out of header properties.
        - Append Info.
        - Write plist file.

        """
        self._gbhdr = Header(self._ifile)
        self._dlink = self._gbhdr.protocol
        self._frame.append(self._gbhdr.info)
        self._ofile(self._gbhdr.info.infotodict(), _name='Global Header')

    def record_frames(self, auto):
        if auto:
            while True:
                try:
                    self._read_frame()
                except EOFError:
                    # quit when EOF
                    break
            self._ifile.close()

    ##########################################################################
    # Methods.
    ##########################################################################

    def _read_frame(self):
        """Read frames.

        - Extract frames and each layer of packets.
        - Make Info object out of frame properties.
        - Append Info.
        - Write plist file.

        """
        self._netwk = None
        self._trans = None
        self._applc = None

        # read frame header
        frame = Frame(self._ifile, self._frnum)
        plist = frame.info.infotodict()

        # make BytesIO from frame package data
        length = frame.info.len
        bytes_ = io.BytesIO(self._ifile.read(length))

        # read link layer
        dlink = self._link_layer(bytes_, length)

        # check link layer protocol
        if not dlink[0]:
            plist['Link Layer'] = dlink[1]
            self._write_record(plist)
            return
        else:
            plist[self._dlink] = dlink[1].info.infotodict()
            self._netwk = dlink[1].protocol
            length -= dlink[1].length

        # read internet layer
        netwk = self._internet_layer(bytes_, length)

        # check internet layer protocol
        if not netwk[0]:
            plist[self._dlink]['Network Layer'] = netwk[1]
            self._write_record(plist)
            return
        else:
            plist[self._dlink][self._netwk] = netwk[1].info.infotodict()
            self._trans = netwk[1].protocol
            length -= netwk[1].length

        # read transport layer
        trans = self._transport_layer(bytes_, length)

        # check transport layer protocol
        if not trans[0]:
            plist[self._dlink][self._netwk]['Transport Layer'] = trans[1]
            self._write_record(plist)
            return
        else:
            plist[self._dlink][self._netwk][self._trans] = trans[1].info.infotodict()
            length -= trans[1].length

        # read application layer
        applc = self._application_layer(bytes_, length)

        # check application layer protocol
        plist[self._dlink][self._netwk][self._trans]['Application Layer'] = applc[1]
        self._write_record(plist)

    def _write_record(self, plist):
        """Write plist & append Info."""
        # write plist
        _fnum = 'Frame {fnum}'.format(fnum=self._frnum)
        plist['protocols'] = self._merge_protocols()
        self._ofile(plist, _name=_fnum)

        # print(_fnum)
        # print(plist['protocols'])
        # print()

        # record frame
        self._frnum += 1
        # info = Info(plist)
        # self._frame.append(info)

    def _merge_protocols(self):
        """Make protocols chain."""
        list_ = [self._dlink, self._netwk, self._trans, self._applc]
        for (i, proto) in enumerate(list_):
            if proto is None:
                return ':'.join(list_[:i])
        return ':'.join(list_)

    def _link_layer(self, _ifile, length):
        """Read link layer."""
        # Other Conditions
        if self._dlink == 'IPv4':
            from .internet.ipv4 import IPv4
            return True, IPv4(_ifile)
        elif self._dlink == 'IPv6':
            from .internet.ipv6 import IPv6
            return True, IPv6(_ifile)
        # Link Layer
        elif self._dlink == 'Ethernet':
            from .link.ethernet import Ethernet
            return True, Ethernet(_ifile)
        else:
            # raise NotImplementedError
            _data = _ifile.read(length) if length else None
            return False, _data

    def _internet_layer(self, _ifile, length):
        """Read internet layer."""
        if self._netwk == 'IPv4':
            from .internet.ipv4 import IPv4
            return True, IPv4(_ifile)
        elif self._netwk == 'IPv6':
            from .internet.ipv6 import IPv6
            return True, IPv6(_ifile)
        else:
            # raise NotImplementedError
            _data = _ifile.read(length) if length else None
            return False, _data

    def _transport_layer(self, _ifile, length):
        """Read transport layer."""
        # IP Suite
        if self._trans == 'IPv4':
            from .internet.ipv4 import IPv4
            return True, IPv4(_ifile)
        elif self._trans == 'IPv6':
            from .internet.ipv6 import IPv6
            return True, IPv6(_ifile)
        # Transport Layer
        elif self._trans == 'TCP':
            from .transport.tcp import TCP
            return True, TCP(_ifile)
        elif self._trans == 'UDP':
            from .transport.udp import UDP
            return True, UDP(_ifile)
        else:
            # raise NotImplementedError
            _data = _ifile.read(length) if length else None
            return False, _data

    def _application_layer(self, _ifile, length):
        """Read application layer."""
        _data = _ifile.read(length) if length else None
        return False, _data