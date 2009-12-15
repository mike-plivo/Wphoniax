#!/usr/bin/env python
# -*- coding: iso-8859-15 -*-

VERSION = "0.3.0"

import sys
import os
import time
import wx
from ConfigParser import ConfigParser
import call
import threading
import string
from Queue import Queue

# mute modes
OPT_MUTE_INCOMING  = 1 # drop incoming frames
OPT_MUTE_OUTGOING  = 2 # drop outgoing frames
OPT_MUTE_BOTH      = 3 # drop incoming and outgoing frames

# events
EVENT_MUTE = 1
EVENT_UNMUTE = 2 
EVENT_HANGUP = 3


def txt2bool(txt):
  if txt is False or txt is True:
    return txt
  if txt == 1 or txt == 0:
    return bool(txt)
  if string.upper(str(txt)) in ('OUI', 'O', 'YES', 'Y', 'TRUE', 'T'):
    return True
  elif string.upper(str(txt)) in ('NON', 'N', 'NO', 'FALSE', 'F'):
    return False
  raise ValueError("Cannot convert '%s' to bool" % str(txt))  



class Account:
  def __init__(self, accountname, user, host, exten, pw=None, context=None, port=4569, dtmfsound=False, muteopt=OPT_MUTE_INCOMING):
    self.accountname = accountname
    self.user = user
    self.host = host
    self.exten = exten
    self.pw = pw
    self.context = context
    self.port = port 
    self.dtmfsound = dtmfsound
    self.mutemode = muteopt

  def get_peer(self):
    peer = self.user
    if self.pw:
      peer += ":%s" % self.pw
    peer += "@%s/%s" % (self.host, self.exten)
    if self.context:
      peer += "@%s" % self.context
    return peer

  def __str__(self):
    return "[%s]\nuser=%s\nhost=%s\nexten=%s\npw=%s\ncontext=%s\nport=%s\ndtmfsound=%s\nmutemode=%s\n" % (str(self.accountname), str(self.user), str(self.host), str(self.exten), str(self.pw), str(self.context), str(self.port), str(self.dtmfsound), str(self.mutemode))


class Frame(wx.Frame):
  def __init__(self, title, accounts, generaloptions):
    self.call = None
    self.eventqueue = Queue()
    self._mute = False
    self.accounts = accounts
    self.generaloptions = generaloptions
    self.accountitems = []
    self.title = title
    self.currentaccount = None
    self._is_local_hangup = False
    self._is_ui_on = False

    for acc in self.accounts:
      self.accountitems.append(acc.accountname)
    # set default account
    self.currentaccount = self.accounts[0]

    # enable mute button ?
    self._enable_mute = True
    if 'mute' in generaloptions:
      if txt2bool(generaloptions['mute']) is False:
        self._enable_mute = False
    
    # set call begin time
    self.callstartat = time.time()

    # frame and main panel
    wx.Frame.__init__(self, None, title=self.title, size=(300, 250))
    self.SetMinSize((300, 250))
    self.Bind(wx.EVT_CLOSE, self.onClose)
    self.panel = wx.Panel(self, -1)
    self.panel.SetBackgroundColour('#4f5049')
    vbox = wx.BoxSizer(wx.VERTICAL)

    # profile listbox 
    self.combox =  wx.ComboBox(self.panel, 6000, size=(150, 40), choices=[], style=wx.CB_READONLY)
    for acc in self.accounts:
      self.combox.Append(acc.accountname)
    self.Bind(wx.EVT_COMBOBOX, self.onSelectAccount, id=6000)
    self.accbox = wx.StaticText(self.panel, -1, ' ', pos=(0, 0), size=(300, -1))
    self.accbox.SetForegroundColour('white')
    self.combox.SetSelection(0)
    self.lbox = wx.BoxSizer(wx.HORIZONTAL)
    self.lbox.Add(self.combox)
    vbox.Add((-1, 10))
    vbox.Add(self.lbox)
    vbox.Add((-1, 10))

    # buttons
    self.button1 = wx.Button(self.panel, 1, 'Appeler', size=(120, 40))
    self.button2 = wx.Button(self.panel, 2, 'Raccrocher', size=(120, 40))
    self.Bind(wx.EVT_BUTTON, self.doCall, id=1)
    self.Bind(wx.EVT_BUTTON, self.doHangup, id=2)

    if self._enable_mute:
      self.mutebutton = wx.Button(self.panel, 3, 'MUTE', size=(80, 40))
      self.Bind(wx.EVT_BUTTON, self.doMute, id=3)
      self.mutebutton.Hide()

    self.bbox = wx.GridSizer(1, 3, 0, 0)
    self.bbox.Add(self.button1, 0, wx.LEFT|wx.EXPAND|wx.ALIGN_CENTER, 4)
    self.button2.Hide()
    vbox.Add(self.bbox)
    vbox.Add((-1, 10))

    # dtmf box
    dtmfbox = wx.BoxSizer(wx.HORIZONTAL)
    dtmfbox = wx.GridSizer(4, 3, 0, 0)
    self.pads = {}
    for x in call.DTMFS:
      if x == '*':
        num_id = 2010
      elif x == '#':
        num_id = 2011
      else:
        num_id = int("200"+x)
      self.pads[x] = wx.Button(self.panel, num_id, x, (30, 30))
      self.Bind(wx.EVT_BUTTON, self.doDtmf, id=num_id)
      dtmfbox.Add(self.pads[x], 0, wx.LEFT, 0)
    vbox.Add(dtmfbox)
    vbox.Add((-1, 10))

    # timer
    self.timer = wx.Timer(self, id=9000)
    self.Bind(wx.EVT_TIMER, self.updateStatus, self.timer, id=9000)
    self.timer.Start(200, False)

    # panel sizer
    self.panel.SetSizer(vbox)
    self.Centre()

  def log_debug(self, msg):
    print "DEBUG: %s" % str(msg)

  def switch_ui_on(self):
    self._is_ui_on = True
    self.bbox.Detach(self.button1)
    self.lbox.Detach(self.combox)
    self.button1.Hide()
    self.combox.Hide()

    self.bbox.Add(self.button2)
    self.lbox.Add(self.accbox)
    self.button2.Show()
    if self._enable_mute:
      self.bbox.Add(self.mutebutton)
      self.switch_ui_mute_on()
      self.mutebutton.Show()
    self.accbox.Show()
    self.accbox.SetLabel("Compte : %s - calling ..." % self.currentaccount.accountname)
    self.bbox.Layout()
    self.lbox.Layout()

  def switch_ui_off(self):
    self._is_ui_on = False
    self.bbox.Detach(self.button2)
    if self._enable_mute:
      self.bbox.Detach(self.mutebutton)
      self.switch_ui_mute_off()
      self.mutebutton.Hide()
    self.lbox.Detach(self.accbox)
    self.button2.Hide()
    self.accbox.Hide()

    self.bbox.Add(self.button1)
    self.lbox.Add(self.combox)
    self.button1.Show()
    self.combox.Show()
    self.accbox.SetLabel(" ")
    self.bbox.Layout()
    self.lbox.Layout()

  def _doCall(self, peer):
    self.log_debug("Start call %s" % peer)
    self._mute = False
    self.call = call.Call(dtmfsound=self.currentaccount.dtmfsound)
    self.call.call(peer)
    while True:
      if not self.call:
        break
      if self.call:
        if self.call.is_call_disconnected():
          break
      try:
        ev = self.eventqueue.get_nowait()
        if ev == EVENT_MUTE:
          if self.currentaccount:
            if self.currentaccount.mutemode == OPT_MUTE_INCOMING:
              self.call.all_unmute()
              self.call.in_mute()
              self.log_debug("Mute Incoming")
            elif self.currentaccount.mutemode == OPT_MUTE_OUTGOING:
              self.call.all_unmute()
              self.call.out_mute()
              self.log_debug("Mute Outgoing")
            elif self.currentaccount.mutemode == OPT_MUTE_BOTH:
              self.call.all_mute()
              self.log_debug("Mute Incoming/Outgoing")
          else:
            self.log_debug("No account selected")
        elif ev == EVENT_UNMUTE:
          if self.currentaccount:
            if self.currentaccount.mutemode == OPT_MUTE_INCOMING:
              self.call.all_unmute()
              self.log_debug("Unmute Incoming")
            elif self.currentaccount.mutemode == OPT_MUTE_OUTGOING:
              self.call.all_unmute()
              self.log_debug("Unmute Outgoing")
            elif self.currentaccount.mutemode == OPT_MUTE_BOTH:
              self.call.all_unmute()
              self.log_debug("Unmute Incoming/Outgoing")
          else:
            self.log_debug("No account selected")
        elif ev == EVENT_HANGUP:
          self._is_local_hangup = True
          break
      except:
        pass
      self.call.sleep(50)

    # end of call loop, hangup !
    self.call.hangup()
    self.call = None
    self.log_debug( "End call %s" % peer)

  def switch_ui_mute_on(self):
    mutetitle = "MUTE"
    if self.currentaccount:
      if self.currentaccount.mutemode == OPT_MUTE_INCOMING:
        mutetitle += " (i)"
      elif self.currentaccount.mutemode == OPT_MUTE_OUTGOING:
        mutetitle += " (o)"
      elif self.currentaccount.mutemode == OPT_MUTE_BOTH:
        mutetitle += " (i/o)"
    self.mutebutton.SetLabel(mutetitle)
    
  def switch_ui_mute_off(self):
    mutetitle = "UNMUTE"
    if self.currentaccount:
      if self.currentaccount.mutemode == OPT_MUTE_INCOMING:
        mutetitle += " (i)"
      elif self.currentaccount.mutemode == OPT_MUTE_OUTGOING:
        mutetitle += " (o)"
      elif self.currentaccount.mutemode == OPT_MUTE_BOTH:
        mutetitle += " (i/o)"
    self.mutebutton.SetLabel(mutetitle)

  def doMute(self, event):
    self.log_debug( "doMute" )
    if self.call:
      if self._mute:
        self.eventqueue.put(EVENT_UNMUTE)
        self._mute = False
        self.switch_ui_mute_on()
      else:
        self.eventqueue.put(EVENT_MUTE)
        self._mute = True
        self.switch_ui_mute_off()
    else:
      self.log_debug( "No call found")

  def updateStatus(self, event):
    if self.call: 
      if self.call.is_call_disconnected():
        if self._is_ui_on:
          self.switch_ui_off()
          if self._is_local_hangup:
            self._is_local_hangup = False
            return
          self.disconnectedPopup()
      else:
        if self.currentaccount:
          period = time.time() - self.callstartat
          if period >= 60.0:
            min = int(period/60)
            sec = int(period - (min*60))
          else:
            min = 0
            sec = int(period)

          if min < 10:
            smin = '0'+str(min)
          else:
            smin = str(min)
          if sec < 10:
            ssec = '0'+str(sec)
          else:
            ssec = str(sec)
          tps = smin+":"+ssec
          self.accbox.SetLabel("Compte: %s - %s" % (self.currentaccount.accountname, tps))

  def onSelectAccount(self, event):
    item = event.GetSelection()
    name = self.accountitems[item]
    for acc in self.accounts:
      if name == acc.accountname:
        self.currentaccount = acc

  def doDtmf(self, event):
    self.log_debug( "doDtmf")
    dtmf = event.GetEventObject().GetLabel()
    if self.call:
      self.call.send_dtmf(str(dtmf))

  def doCall(self, event):
    self.log_debug( "doCall")
    if not self.currentaccount:
      self.noaccountPopup()
      return
    if self.call and not self.call.is_call_disconnected():
      self.log_debug( "A call is already running !!!")
      return
    peer = self.currentaccount.get_peer()
    playdtmf = self.currentaccount.dtmfsound
    self.callth = threading.Thread(target=self._doCall, args=(peer, ))
    self.callth.start()
    self.callstartat = time.time()
    self.switch_ui_on()

  def doHangup(self, event):
    self.log_debug( "doHangup")
    if self.call:
      self.eventqueue.put(EVENT_HANGUP)
    else:
      self.log_debug("No call found")

  def onClose(self, event):
    dw = wx.MessageDialog(self, 
        "Quitter %s ?" % self.title,
        "Quitter", wx.OK|wx.CANCEL|wx.ICON_QUESTION)
    dw.Center()
    result = dw.ShowModal()
    dw.Destroy()
    if result == wx.ID_OK:
      if self.call:
        self.call.hangup()
        self.call = None
        time.sleep(0.2)
      self.Destroy()

  def disconnectedPopup(self):
    msg = u"L'appel est terminé"
    w = wx.MessageDialog(self,message=msg,style=wx.ICON_WARNING)
    w.SetTitle("Fin de la connexion")
    w.ShowModal()
    w.Center()
    w.Destroy()

  def noaccountPopup(self):
    msg = "Choisissez un compte !"
    w = wx.MessageDialog(self,message=msg,style=wx.ICON_WARNING)
    w.SetTitle(u"Aucun compte n'a été sélectionné")
    w.ShowModal()
    w.Center()
    w.Destroy()

  def accountPopup(self, accountname):
    msg = u"Vous avez sélectionné le compte : %s" % accountname
    w = wx.MessageDialog(self,message=msg,style=wx.ICON_INFORMATION)
    w.SetTitle("Compte")
    w.ShowModal()
    w.Center()
    w.Destroy()


def errorPopup(msg):
  w = wx.MessageDialog(None,message=msg,style=wx.ICON_ERROR)
  w.SetTitle("Erreur")
  w.ShowModal()
  w.Center()
  w.Destroy()



if __name__ == '__main__':
  app = wx.App(redirect=True)
  if not os.path.isfile("wphoniax.ini"):
    errorPopup("Fichier de configuration wphoniax.ini manquant !")
    sys.exit(1)
  cfg = ConfigParser()
  cfg.read("wphoniax.ini")
  sections = cfg.sections()
  if len(sections) == 0:
    errorPopup("Aucun compte dans wphoniax.ini !")
    sys.exit(1)

  # set valid accounts
  accounts = []
  generaloptions = {}
  for section in sorted(sections):
    if section == 'general':
      for opt in cfg.items('general'):
        var = opt[0]
        val = opt[1]
        generaloptions[var] = val
    else:
      try:
        accountname = section
        if accountname in accounts:
          continue
        user = cfg.get(section, "user")
        if not cfg.has_option(section, "password"):
          password = None
        else:
          password = cfg.get(section, "password")
        if not password.strip():
          password = None
        exten = cfg.get(section, "exten")
        context = cfg.get(section, "context")
        host = cfg.get(section, "host")
        if not cfg.has_option(section, "port"):
          port = 4569
        else:
          port = cfg.getint(section, "port")
        if not cfg.has_option(section, "dtmfsound"):
          dtmfsound = False
        else:
          dtmfsound = txt2bool(cfg.get(section, "dtmfsound"))
        if not cfg.has_option(section, "mutemode"):
          mutemode = OPT_MUTE_INCOMING
        else:
          mutemode = cfg.getint(section, "mutemode")
        account = Account(accountname, user, host, exten, password, context, port, dtmfsound, muteopt=mutemode)
        print str(account)
        accounts.append(account)
      except Exception, err:
        errorPopup("Probleme de configuration du compte %s :\n(%s)" % (section, str(err)))
        sys.exit(1)

  if len(accounts) == 0:
    errorPopup("Aucun compte valide dans wphoniax.ini !")
    sys.exit(1)

  # build main frame
  top = Frame("Wphoniax %s" % VERSION, accounts, generaloptions)
  # set icon
  img = wx.Image("wphoniax.png", wx.BITMAP_TYPE_PNG)
  img.ConvertAlphaToMask()
  img.Rescale(32, 32)
  blogo = img.ConvertToBitmap()
  logo = wx.IconFromBitmap(blogo)
  top.SetIcon(logo)
  top.Show()
  # run
  app.MainLoop()

