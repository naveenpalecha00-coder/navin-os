#!/usr/bin/python3
import gi,json,subprocess,threading,pathlib,tempfile,base64,os,urllib.request,urllib.parse
from navin_logic import automation

gi.require_version('Gtk','3.0');gi.require_version('WebKit2','4.1')
from gi.repository import Gtk,WebKit2,GLib
class AI(Gtk.Window):
 def __init__(self):
  super().__init__(title='NAVIN AI · Build 8');self.set_default_size(880,680);self.connect('destroy',self.close)
  self.manager=WebKit2.UserContentManager();self.manager.register_script_message_handler('native');self.manager.connect('script-message-received::native',self.message)
  self.web=WebKit2.WebView.new_with_user_content_manager(self.manager);self.web.get_settings().set_enable_developer_extras(False);self.web.get_settings().set_enable_write_console_messages_to_stdout(False)
  self.web.connect('decide-policy',self.policy);self.add(self.web);self.recording=None;self.processes=[]
  self.web.load_uri(pathlib.Path('/usr/share/navin/ai/index.html').as_uri());self.show_all()
 def close(self,*_):
  for p in self.processes:
   if p.poll() is None:p.terminate()
  Gtk.main_quit()
 def policy(self,view,decision,kind):
  if kind==WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
   uri=decision.get_navigation_action().get_request().get_uri()
   if not uri.startswith('file:///usr/share/navin/ai/'):
    decision.ignore();return True
  return False
 def send(self,id,data):
  # JSON-encode data as arguments, never concatenate executable user text.
  script='window.nativeResult('+json.dumps(id)+','+json.dumps(data)+');'
  GLib.idle_add(self.web.evaluate_javascript,script,-1,None,None,None,None,None)
 def message(self,manager,result):
  try:
   request=json.loads(result.get_js_value().to_string());id=request['id'];action=request['action'];payload=request.get('payload',{})
   if action=='record-start':
    if self.recording and self.recording.poll() is None:raise ValueError('Recording already active')
    self.audio=tempfile.NamedTemporaryFile(suffix='.wav',delete=False);self.audio.close()
    self.recording=subprocess.Popen(['ffmpeg','-y','-f','pulse','-i','default','-t','30','-ac','1','-ar','16000',self.audio.name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);self.processes.append(self.recording);self.send(id,{'recording':True});return
   threading.Thread(target=self.task,args=(id,action,payload),daemon=True).start()
  except Exception as e:self.send(request.get('id','error') if 'request' in locals() else 'error',{'error':str(e)})
 def task(self,id,action,payload):
  try:
   if action=='record-stop':
    if not self.recording:raise ValueError('No active microphone recording')
    if self.recording.poll() is None:self.recording.send_signal(2)
    self.recording.wait(timeout=10);payload={'audio':base64.b64encode(pathlib.Path(self.audio.name).read_bytes()).decode(),'model':payload.get('model','navin-1')};os.unlink(self.audio.name);action='transcribe'
   if action=='automation':
    command=automation(payload.get('text',''))
    commands={'mute':['pactl','set-sink-mute','@DEFAULT_SINK@','1'],'brightness':['brightnessctl','set','+10%'],'ram-boost':['pkexec','/usr/local/lib/navin/navin-repair','ram-boost'],'mic':['navin-mic-fix','--test']}
    if command not in commands:raise ValueError('Only mute volume, increase brightness, boost RAM and test microphone are available locally.')
    # Explicit user confirmation, not autonomous execution of model output.
    def confirm():
     d=Gtk.MessageDialog(transient_for=self,modal=True,buttons=Gtk.ButtonsType.OK_CANCEL,text='Run local action: '+payload.get('text','')+'?');ok=d.run()==Gtk.ResponseType.OK;d.destroy()
     if ok:threading.Thread(target=self.local,args=(id,commands[command]),daemon=True).start()
     else:self.send(id,{'error':'Action cancelled'})
    GLib.idle_add(confirm);return
   if action=='wallpaper':
    folder=pathlib.Path.home()/'Pictures/NAVIN AI';folder.mkdir(parents=True,exist_ok=True)
    image=folder/'wallpaper.png'
    if payload.get('b64_json'):content=base64.b64decode(payload['b64_json'],validate=True)
    else:
     url=payload.get('url','');parsed=urllib.parse.urlsplit(url)
     if parsed.scheme!='https':raise ValueError('Wallpaper URL must use HTTPS')
     with urllib.request.urlopen(url,timeout=60) as r:content=r.read(20*1024*1024+1)
    if len(content)>20*1024*1024:raise ValueError('Image too large')
    if not (content.startswith(b'\x89PNG') or content.startswith(b'\xff\xd8') or content.startswith(b'RIFF')):raise ValueError('Unsupported image file')
    image.write_bytes(content)
    properties=subprocess.check_output(['xfconf-query','-c','xfce4-desktop','-l'],text=True).splitlines()
    for p in properties:
     if p.endswith('/last-image'):subprocess.run(['xfconf-query','-c','xfce4-desktop','-p',p,'-s',str(image)],check=True)
    self.send(id,{'wallpaper':str(image)});return
   if action not in ('models','chat','speech','transcribe','image'):raise ValueError('Unsupported request')
   p=subprocess.Popen(['pkexec','/usr/local/lib/navin/navin-ai-request'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);self.processes.append(p)
   p.stdin.write(json.dumps({'action':action,'payload':payload}));p.stdin.close()
   for line in p.stdout:
    try:self.send(id,json.loads(line))
    except json.JSONDecodeError:pass
   rc=p.wait()
   if rc and p.stderr:self.send(id,{'error':p.stderr.read()[:1000] or 'NAVIN request failed'})
  except Exception as e:self.send(id,{'error':str(e)})
 def local(self,id,args):
  try:
   result=subprocess.run(args,capture_output=True,text=True);self.send(id,{'text':result.stdout or ('Action completed' if result.returncode==0 else result.stderr)})
  except Exception as e:self.send(id,{'error':str(e)})
AI();Gtk.main()
