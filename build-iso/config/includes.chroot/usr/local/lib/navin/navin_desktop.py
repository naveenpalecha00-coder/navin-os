#!/usr/bin/python3
import gi, os, re, sys, json, subprocess, threading, pathlib, urllib.request, ast, operator, time, secrets
from navin_logic import package_name, release_build, newer_patch, newer_os_release, BUILD, VERSION, REPO

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk

def run(args):
 p=subprocess.run(args, capture_output=True, text=True)
 if p.returncode: raise RuntimeError(p.stderr.strip() or p.stdout.strip() or 'Command failed')
 return p.stdout.strip()
def status(args):
 try: return run(args)
 except Exception: return ''
def launch(args): subprocess.Popen(args)
class Window(Gtk.Window):
 def __init__(self,title):
  super().__init__(title=title); self.set_default_size(640,520); self.connect('destroy',Gtk.main_quit)
  self.box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12); self.box.set_border_width(18); self.add(self.box)
  self.status=Gtk.Label(xalign=0); self.status.set_line_wrap(True)
 def button(self,label,fn,box=None):
  b=Gtk.Button(label=label); b.connect('clicked',lambda _:fn()); (box or self.box).pack_start(b,False,False,0); return b
 def work(self,fn,done=None):
  def task():
   try: value=fn(); GLib.idle_add(done or self.status.set_text,str(value))
   except Exception as e: GLib.idle_add(self.status.set_text,str(e))
  threading.Thread(target=task,daemon=True).start()
 def finish(self): self.box.pack_end(self.status,False,False,0); self.show_all()
class Store(Window):
 def __init__(self):
  super().__init__('NAVIN App Store'); self.set_default_size(780,640)
  self.catalog=json.loads(pathlib.Path('/usr/local/lib/navin/catalog.json').read_text()); self.available={}; self.installed=set()
  self.category=Gtk.ComboBoxText(); self.category.append_text('All'); [self.category.append_text(k) for k in self.catalog]; self.category.set_active(0); self.category.connect('changed',lambda _:self.render()); self.box.pack_start(self.category,False,False,0)
  self.search=Gtk.SearchEntry(); self.search.connect('search-changed',lambda _:self.render()); self.box.pack_start(self.search,False,False,0)
  scroll=Gtk.ScrolledWindow(); self.rows=Gtk.ListBox(); scroll.add(self.rows); self.box.pack_start(scroll,True,True,0)
  self.progress=Gtk.ProgressBar(); self.box.pack_start(self.progress,False,False,0)
  self.output=Gtk.TextView(editable=False,monospace=True); log=Gtk.ScrolledWindow(); log.set_min_content_height(100); log.add(self.output); self.box.pack_start(log,False,True,0)
  self.button('Refresh catalogue',self.refresh); self.button('Flathub apps (Flatpak)…',lambda:launch(['navin-app-store','flathub']))
  self.busy=False; self.status.set_text('Reading APT catalogue…'); self.finish(); self.refresh()
 def refresh(self):
  def get():
   packages=sorted({p for items in self.catalog.values() for p in items})
   result=subprocess.run(['apt-cache','show',*packages],capture_output=True,text=True)
   if not result.stdout.strip():raise RuntimeError(result.stderr.strip() or 'APT metadata unavailable. Refresh catalogue after updating package lists.')
   data=result.stdout; available={}
   for block in data.split('\n\n'):
    fields=dict(line.split(': ',1) for line in block.splitlines() if ': ' in line and not line.startswith(' '))
    if 'Package' in fields: available[fields['Package']]=fields.get('Description','')
   installed=run(['dpkg-query','-W','-f=${Package}\t${db:Status-Status}\n'])
   return available,{x.split('\t')[0] for x in installed.splitlines() if x.endswith('\tinstalled')}
  def task():
   try:
    self.available,self.installed=get(); GLib.idle_add(self.render)
   except Exception as e: GLib.idle_add(self.status.set_text,str(e))
  threading.Thread(target=task,daemon=True).start()
 def render(self):
  for child in self.rows.get_children(): self.rows.remove(child)
  cat=self.category.get_active_text(); selected=self.catalog.get(cat,sorted({p for v in self.catalog.values() for p in v})); q=self.search.get_text().lower(); count=0
  for p in selected:
   if p not in self.available or q not in (p+' '+self.available[p]).lower(): continue
   count+=1; row=Gtk.Box(spacing=8); row.set_border_width(8)
   label=Gtk.Label(label=p+'\n'+self.available[p],xalign=0); label.set_line_wrap(True); label.set_max_width_chars(48); row.pack_start(label,True,True,0)
   b=Gtk.Button(label='Uninstall' if p in self.installed else 'Install'); b.set_sensitive(not self.busy); b.connect('clicked',lambda _,pkg=p:self.transaction(pkg)); row.pack_end(b,False,False,0)
   if p in self.installed:
    self.button('Launch',lambda pkg=p:self.launch_package(pkg),row)
   self.rows.add(row)
  self.rows.show_all(); self.status.set_text(f'{count} applications available from configured APT repositories')
 def launch_package(self,p):
  try:
   files=run(['dpkg','-L',p]).splitlines(); desktop=next((f for f in files if f.startswith('/usr/share/applications/') and f.endswith('.desktop')),None)
   if desktop: launch(['gio','launch',desktop])
   else: self.status.set_text('This package has no graphical launcher.')
  except Exception as e:self.status.set_text(str(e))
 def transaction(self,p):
  if self.busy or not package_name(p): return
  dialog=Gtk.MessageDialog(transient_for=self,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.OK_CANCEL,text=('Remove ' if p in self.installed else 'Install ')+p+'?')
  response=dialog.run(); dialog.destroy()
  if response!=Gtk.ResponseType.OK:return
  action='remove' if p in self.installed else 'install'; self.busy=True; self.render(); self.progress.set_fraction(0); self.output.get_buffer().set_text('')
  pulse=GLib.timeout_add(120,lambda: (self.progress.pulse() or True) if self.busy else False)
  def task():
   try:
    env=dict(os.environ,DEBIAN_FRONTEND='noninteractive'); proc=subprocess.Popen(['pkexec','/usr/local/lib/navin/navin-repair',action,p],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=env)
    for line in proc.stdout:
     GLib.idle_add(self.append,line)
    rc=proc.wait(); GLib.idle_add(self.complete,rc)
   except Exception as e:GLib.idle_add(self.complete,1,str(e))
  threading.Thread(target=task,daemon=True).start()
 def append(self,line):
  b=self.output.get_buffer(); b.insert(b.get_end_iter(),line)
 def complete(self,rc,error=''):
  self.busy=False; self.progress.set_fraction(1 if rc==0 else 0); self.status.set_text('Transaction finished' if rc==0 else 'APT failed: '+error); self.refresh()
class Flathub(Window):
 """Real Flatpak/Flathub search, install, update, remove and launch with streamed progress."""
 def __init__(self):
  super().__init__('NAVIN App Store — Flathub'); self.set_default_size(780,640); self.busy=False; self.installed=set()
  self.search=Gtk.SearchEntry(placeholder_text='Search Flathub (e.g. spotify, gimp, obs)'); self.search.connect('activate',lambda _:self.find()); self.box.pack_start(self.search,False,False,0)
  scroll=Gtk.ScrolledWindow(); self.rows=Gtk.ListBox(); scroll.add(self.rows); self.box.pack_start(scroll,True,True,0)
  self.progress=Gtk.ProgressBar(show_text=True); self.box.pack_start(self.progress,False,False,0)
  self.output=Gtk.TextView(editable=False,monospace=True); log=Gtk.ScrolledWindow(); log.set_min_content_height(110); log.add(self.output); self.box.pack_start(log,False,True,0)
  bar=Gtk.Box(spacing=6); self.box.pack_start(bar,False,False,0); self.button('Show installed',self.list_installed,bar); self.button('Update all Flatpak apps',lambda:self.transaction(['update','-y','--noninteractive'],'Update'),bar)
  self.finish(); self.status.set_text('Type a name and press Enter. Apps come from Flathub; each is sandboxed.'); self.list_installed()
 def flatpak(self,*a): return run(['flatpak',*a])
 def list_installed(self):
  def get(): return [l.split('\t') for l in self.flatpak('list','--app','--columns=application,name,version').splitlines() if l.strip()]
  def show(rows):
   self.installed={r[0] for r in rows}; self.render([(r[0],r[1] if len(r)>1 else r[0],'Installed '+(r[2] if len(r)>2 else ''),'') for r in rows]); self.status.set_text(f'{len(rows)} Flatpak apps installed')
  threading.Thread(target=lambda:self._bg(get,show),daemon=True).start()
 def _bg(self,fn,done):
  try: v=fn(); GLib.idle_add(done,v)
  except Exception as e: GLib.idle_add(self.status.set_text,str(e))
 def find(self):
  q=self.search.get_text().strip()
  if not q: return
  self.status.set_text('Searching Flathub…')
  def get():
   out=self.flatpak('search','--columns=application,name,description,version',q)
   return [(l.split('\t')+['','','',''])[:4] for l in out.splitlines() if '\t' in l]
  def show(rows):
   self.render([(a,n,v,d) for a,n,d,v in rows][:60]); self.status.set_text(f'{len(rows)} results on Flathub' if rows else 'No results (check internet; Flathub data downloads on first search)')
  threading.Thread(target=lambda:self._bg(get,show),daemon=True).start()
 def render(self,items):
  for c in self.rows.get_children(): self.rows.remove(c)
  for app,name,ver,desc in items:
   r=Gtk.Box(spacing=8); r.set_border_width(8); l=Gtk.Label(label=f'{name}  ({app}) {ver}\n{desc}',xalign=0); l.set_line_wrap(True); l.set_max_width_chars(60); r.pack_start(l,True,True,0)
   inst=app in self.installed; b=Gtk.Button(label='Remove' if inst else 'Install'); b.set_sensitive(not self.busy)
   b.connect('clicked',lambda _,a=app,i=inst:self.transaction(['uninstall','-y','--noninteractive',a] if i else ['install','-y','--noninteractive','flathub',a],('Remove ' if i else 'Install ')+a))
   r.pack_end(b,False,False,0)
   if inst: self.button('Open',lambda a=app:launch(['flatpak','run',a]),r)
   self.rows.add(r)
  self.rows.show_all()
 def transaction(self,args,title):
  if self.busy: return
  d=Gtk.MessageDialog(transient_for=self,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.OK_CANCEL,text=title+'?'); ok=d.run()==Gtk.ResponseType.OK; d.destroy()
  if not ok: return
  self.busy=True; self.output.get_buffer().set_text(''); self.progress.set_fraction(0)
  def task():
   p=subprocess.Popen(['flatpak',*args],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
   buf=''
   while True:
    ch=p.stdout.read(1)
    if not ch: break
    buf+=ch
    if ch in '\r\n':
     line=buf.strip(); buf=''
     m=re.search(r'(\d{1,3})%',line)
     if m: GLib.idle_add(self.progress.set_fraction,int(m.group(1))/100)
     if line: GLib.idle_add(self.append,line+'\n')
   rc=p.wait(); GLib.idle_add(self.done,rc)
  threading.Thread(target=task,daemon=True).start()
 def append(self,line):
  b=self.output.get_buffer(); b.insert(b.get_end_iter(),line)
 def done(self,rc):
  self.busy=False; self.progress.set_fraction(1 if rc==0 else 0); self.status.set_text('Finished' if rc==0 else f'Flatpak failed (exit {rc}) — see the log above'); self.list_installed()
class Controls(Window):
 def __init__(self):
  super().__init__('NAVIN Control Center')
  self.button('Wi-Fi',lambda:self.work(lambda:run(['nmcli','radio','wifi','off' if run(['nmcli','radio','wifi'])=='enabled' else 'on'])))
  self.button('Wi-Fi networks',lambda:launch(['nm-connection-editor']))
  self.button('Bluetooth devices & battery',lambda:launch(['blueman-manager']))
  self.button('Bluetooth on / off',lambda:self.work(self.bluetooth))
  for title,fn,initial in [('Volume',lambda v:run(['pactl','set-sink-volume','@DEFAULT_SINK@',str(int(v))+'%']),self.volume()),('Brightness',lambda v:run(['brightnessctl','set',str(int(v))+'%']),self.brightness())]:
   self.box.pack_start(Gtk.Label(label=title,xalign=0),False,False,0); scale=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0 if title=='Volume' else 5,100,1); scale.set_value(initial); scale.connect('value-changed',lambda s,f=fn:self.work(lambda:f(s.get_value()))); self.box.pack_start(scale,False,False,0)
  self.button('Night Light',self.night); self.button('Mobile hotspot',self.hotspot); self.button('RAM booster',lambda:self.work(lambda:run(['pkexec','/usr/local/lib/navin/navin-repair','ram-boost'])))
  self.button('Fan & Cooling',lambda:launch(['navin-fan-control'])); self.button('Devices',lambda:launch(['navin-device-manager'])); self.button('Privacy kill switch',self.privacy)
  self.turbo=self.button('Turbo Mode: '+('ON' if status(['navin-turbo','status'])=='on' else 'OFF'),self.toggle_turbo)
  for label,cmd in [('Quick Share',['navin-quick-share']),('Screen recorder',['navin-recorder']),('Snipping tool',['xfce4-screenshooter','-r','-c']),('Snapshot & restore',['navin-snapshot']),('Private Vault',['navin-vault']),('Theme & dock glass',['navin-theme','menu'])]:
   self.button(label,lambda c=cmd:launch(c))
  self.finish(); GLib.timeout_add_seconds(5,self.battery); self.battery()
 def toggle_turbo(self):
  self.work(lambda:run(['navin-turbo','toggle']),lambda _:self.turbo.set_label('Turbo Mode: '+('ON' if status(['navin-turbo','status'])=='on' else 'OFF')))
 def volume(self):
  try:return int(run(['pactl','get-sink-volume','@DEFAULT_SINK@']).split('%')[0].split()[-1])
  except:return 50
 def brightness(self):
  try:return int(run(['brightnessctl','get']))*100/int(run(['brightnessctl','max']))
  except:return 50
 def bluetooth(self):
  on='Powered: yes' in run(['bluetoothctl','show']); return run(['bluetoothctl','power','off' if on else 'on'])
 def night(self):
  if subprocess.run(['pgrep','-x','redshift'],stdout=subprocess.DEVNULL).returncode==0: subprocess.run(['pkill','-x','redshift']); launch(['redshift','-x'])
  else:launch(['redshift','-P','-O','4000'])
 def hotspot(self):
  password=secrets.token_urlsafe(9)
  self.work(lambda:run(['nmcli','device','wifi','hotspot','ssid','NAVIN Hotspot','password',password]),lambda _:self.status.set_text('Hotspot password: '+password))
 def privacy(self):
  subprocess.run(['pactl','set-source-mute','@DEFAULT_SOURCE@','1'])
  # Only signal this user's processes actually holding camera devices.
  result=subprocess.run(['fuser',*map(str,pathlib.Path('/dev').glob('video*'))],capture_output=True,text=True)
  for pid in result.stdout.split():
   try:
    if pathlib.Path('/proc/'+pid).stat().st_uid==os.getuid():os.kill(int(pid),15)
   except (OSError,ValueError):pass
  self.status.set_text('Microphone muted; current user camera applications closed.')
 def battery(self):
  batteries=list(pathlib.Path('/sys/class/power_supply').glob('BAT*/capacity')); info=['Battery '+p.read_text().strip()+'%' for p in batteries]
  try:
   devices=run(['bluetoothctl','devices','Connected']).splitlines()
   for d in devices:
    parts=d.split(); data=run(['bluetoothctl','info',parts[1]])
    info.append(parts[2]+' '+next((l.strip() for l in data.splitlines() if 'Battery Percentage' in l),'battery not reported'))
  except:pass
  self.status.set_text(' · '.join(info) or 'Battery not reported'); return True
class Fan(Window):
 def __init__(self):
  super().__init__('NAVIN Fan & Cooling'); self.sensor=Gtk.Label(xalign=0); self.sensor.set_line_wrap(True); self.box.pack_start(self.sensor,True,True,0)
  self.button('Open fan speed slider (System Center)',lambda:launch(['navin-center','fan']))
  for mode in ('silent','balanced','cooling','auto','restore'):self.button(mode.title(),lambda m=mode:self.work(lambda:run(['pkexec','/usr/local/lib/navin/navin-fan',m])))
  self.finish(); GLib.timeout_add_seconds(3,self.refresh); self.refresh()
 def refresh(self):
  try:self.sensor.set_text(run(['/usr/local/lib/navin/navin-fan','status'])+'\n\n'+run(['sensors']))
  except:self.sensor.set_text('Thermal sensors not exposed by this hardware')
  return True
class Devices(Window):
 def __init__(self):
  super().__init__('NAVIN Device Manager'); tree=Gtk.TreeStore(str,str)
  for title,args in [('CPU',['lscpu']),('GPU / Audio / Wi-Fi',['lspci','-nnk']),('USB / Camera',['lsusb']),('Touchpad / Keyboard',['xinput','list'])]:
   parent=tree.append(None,[title,''])
   try:
    for line in run(args).splitlines():tree.append(parent,[line,''])
   except Exception as e:tree.append(parent,[str(e),''])
  view=Gtk.TreeView(model=tree); view.append_column(Gtk.TreeViewColumn('Hardware',Gtk.CellRendererText(),text=0)); scroll=Gtk.ScrolledWindow(); scroll.add(view); self.box.pack_start(scroll,True,True,0); self.finish()
class Display(Window):
 def __init__(self):
  super().__init__('Project'); self.set_default_size(360,320)
  for mode in ('PC Screen Only','Duplicate','Extend','Second Screen Only'):self.button(mode,lambda m=mode:self.work(lambda:self.apply(m)))
  self.finish()
 def apply(self,mode):
  outputs=[line.split()[0] for line in run(['xrandr','--query']).splitlines() if ' connected' in line]
  internal=next((o for o in outputs if o.startswith(('eDP','LVDS','DSI'))),outputs[0] if outputs else None); external=next((o for o in outputs if o!=internal),None)
  if not internal:raise RuntimeError('No connected display')
  if mode!='PC Screen Only' and not external:raise RuntimeError('Connect a second display first')
  if mode=='PC Screen Only':args=['--output',internal,'--auto','--primary']+sum((['--output',o,'--off'] for o in outputs if o!=internal),[])
  elif mode=='Second Screen Only':args=['--output',external,'--auto','--primary','--output',internal,'--off']
  else:args=['--output',internal,'--auto','--primary','--output',external,'--auto','--same-as' if mode=='Duplicate' else '--right-of',internal]
  return run(['xrandr',*args]) or mode
class Search(Window):
 def __init__(self):
  super().__init__('NAVIN Spotlight'); self.set_default_size(580,430); self.entry=Gtk.SearchEntry(); self.entry.connect('search-changed',self.search); self.box.pack_start(self.entry,False,False,0); self.results=Gtk.ListBox(); self.results.connect('row-activated',self.activate); self.box.pack_start(self.results,True,True,0); self.actions=[]; self.finish()
 def search(self,_):
  for c in self.results.get_children():self.results.remove(c)
  q=self.entry.get_text().strip(); self.actions=[]
  if not q:return
  # Arithmetic AST permits numbers and operators only; never eval user text.
  try:
   ops={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv}
   def calc(n):
    if isinstance(n,ast.Constant) and type(n.value) in (int,float):return n.value
    if isinstance(n,ast.BinOp) and type(n.op) in ops:return ops[type(n.op)](calc(n.left),calc(n.right))
    raise ValueError()
   self.result(str(calc(ast.parse(q[:100],mode='eval').body)),lambda:None)
  except:pass
  for p in pathlib.Path('/usr/share/applications').glob('*.desktop'):
   text=p.read_text(errors='replace'); name=next((l[5:] for l in text.splitlines() if l.startswith('Name=')),p.stem)
   if q.lower() in name.lower():self.result(name,lambda path=str(p):launch(['gio','launch',path]))
   if len(self.actions)>=12:break
  found=0
  for base in ('Desktop','Documents','Downloads'):
   for folder,dirs,files in os.walk(pathlib.Path.home()/base):
    dirs[:]=[d for d in dirs if not d.startswith('.')]
    for f in files:
     if q.lower() in f.lower():self.result(f,lambda p=str(pathlib.Path(folder)/f):launch(['xdg-open',p])); found+=1
     if found>=8:break
    if found>=8:break
  import urllib.parse
  self.result('Search web: '+q,lambda:launch(['navin-chrome','https://www.google.com/search?q='+urllib.parse.quote(q)])); self.results.show_all()
 def result(self,title,fn):self.actions.append(fn); self.results.add(Gtk.Label(label=title,xalign=0,margin=8))
 def activate(self,_,row):self.actions[row.get_index()](); self.destroy()
class Updater(Window):
 def __init__(self):
  super().__init__('NAVIN System Updater'); self.remote=None; self.progress=Gtk.ProgressBar(); self.box.pack_start(self.progress,False,False,0); self.check=self.button('Check GitHub releases',self.query); self.install=self.button('Download & apply verified patch',self.apply); self.install.set_sensitive(False); self.button('Debian package updates',lambda:launch(['x-terminal-emulator','-e','sudo','/usr/local/lib/navin/navin-repair','upgrade'])); self.restart=self.button('Restart Now',lambda:launch(['systemctl','reboot'])); self.restart.set_sensitive(False); self.finish(); self.query()
 def query(self):
  def fetch():
   req=urllib.request.Request('https://api.github.com/repos/'+REPO+'/releases',headers={'Accept':'application/vnd.github+json','User-Agent':'NAVIN-OS-Updater'})
   with urllib.request.urlopen(req,timeout=30) as response: rows=json.load(response)
   current=int(pathlib.Path('/etc/navin/build').read_text().strip()); self.os_release=newer_os_release(rows)
   return newer_patch(rows,current)
  def task():
   try:self.remote=fetch(); GLib.idle_add(self.ready)
   except Exception as e:GLib.idle_add(self.status.set_text,str(e))
  threading.Thread(target=task,daemon=True).start()
 def ready(self):
  self.install.set_sensitive(bool(self.remote)); msg=[]
  if self.remote:msg.append('Update '+self.remote['tag_name']+' is ready: '+((self.remote.get('body') or '').strip().splitlines() or ['NAVIN tools and settings'])[0][:120])
  if getattr(self,'os_release',None):
   msg.append('New NAVIN version '+self.os_release['tag_name']+' is available (new ISO - install it from a USB drive). Opening the download page...'); launch(['xdg-open',self.os_release['html_url']])
  self.status.set_text('\n'.join(msg) or 'NAVIN '+VERSION+' is up to date (checked GitHub just now)')
 def apply(self):
  if not self.remote:return
  dialog=Gtk.MessageDialog(transient_for=self,modal=True,buttons=Gtk.ButtonsType.OK_CANCEL,text='Apply configuration and tools from '+self.remote['tag_name']+'? Back up important files first.'); reply=dialog.run(); dialog.destroy()
  if reply!=Gtk.ResponseType.OK:return
  self.install.set_sensitive(False)
  def task():
   import tempfile,hashlib
   try:
    with tempfile.TemporaryDirectory(prefix='navin-update-') as d:
     assets={a['name']:a['browser_download_url'] for a in self.remote['assets']}; path=pathlib.Path(d)/'navin-update.tar.gz'
     with urllib.request.urlopen(assets[path.name],timeout=120) as r,open(path,'wb') as f:
      total=int(r.headers.get('Content-Length',0)); received=0
      while True:
       chunk=r.read(1024*1024)
       if not chunk:break
       f.write(chunk); received+=len(chunk)
       if received>100*1024*1024:raise ValueError('Patch exceeds 100 MB safety limit')
       if total:GLib.idle_add(self.progress.set_fraction,min(1,received/total))
     with urllib.request.urlopen(assets[path.name+'.sha256'],timeout=30) as r:expected=r.read(1024).decode().split()[0]
     digest=hashlib.sha256(path.read_bytes()).hexdigest()
     if digest!=expected:raise ValueError('Patch checksum mismatch')
     output=run(['pkexec','/usr/local/lib/navin/navin-apply-update',str(path),digest,str(release_build(self.remote['tag_name']))]); GLib.idle_add(self.applied,output)
   except Exception as e:GLib.idle_add(self.status.set_text,str(e))
  threading.Thread(target=task,daemon=True).start()
 def applied(self,text):self.status.set_text(text); self.restart.set_sensitive(True); launch(['notify-send','NAVIN updated','Restart when ready'])
class Welcome(Window):
 def __init__(self):
  super().__init__('Welcome to NAVIN 2.1'); self.box.pack_start(Gtk.Image.new_from_file('/usr/share/pixmaps/navin-os-logo.png'),True,True,0); self.box.pack_start(Gtk.Label(label='Namaste, Navin!\nYour PC. Your OS. Your Freedom.'),False,False,0)
  for label,cmd in [('Connect Wi-Fi','nm-connection-editor'),('NAVIN AI','navin-ai-desktop'),('App Store','navin-app-store'),('Install NAVIN OS','install-debian'),("What's new in NAVIN 2.1",'navin-center'),('NAVIN Toolbox','navin-toolbox')]:self.button(label,lambda c=cmd:launch([c,'whatsnew'] if c=='navin-center' else [c]))
  self.button('Done',self.destroy); self.finish(); launch(['paplay','/usr/share/sounds/freedesktop/stereo/desktop-login.oga'])
mode=sys.argv[1] if len(sys.argv)>1 else 'controls'
if mode=='welcome' and '--autostart' in sys.argv:
 flag=pathlib.Path.home()/'.config/navin/welcome-done'
 if flag.exists():sys.exit(0)
 flag.parent.mkdir(parents=True,exist_ok=True); flag.touch()
if mode=='store' and 'flathub' in sys.argv: mode='flathub'
classes={'flathub':Flathub,'store':Store,'controls':Controls,'fan':Fan,'devices':Devices,'display':Display,'search':Search,'updater':Updater,'welcome':Welcome}
classes[mode](); Gtk.main()
