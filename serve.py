#!/usr/bin/env python3
"""Serve the Glow Spa playable to phones on the same wifi, and open a QR page to scan."""
import gzip, http.server, os, socket, socketserver, sys, threading, webbrowser

PORT = int(os.environ.get("PORT", "8000"))
HERE = os.path.dirname(os.path.abspath(__file__))

def lan_ip():
    for target in ("8.8.8.8", "10.255.255.255", "192.168.255.255"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target, 1))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            pass
        finally:
            s.close()
    return None

import json, time
LOG = os.path.join(HERE, "server-log.txt")
_lock = threading.Lock()
def log(line):
    stamp = time.strftime("%H:%M:%S")
    with _lock:
        with open(LOG, "a") as f:
            f.write("%s %s\n" % (stamp, line))

DIAG = b"""<script>(function(){var t0=Date.now();function b(e,d){try{var x=new XMLHttpRequest();x.open('POST','/beacon',true);x.setRequestHeader('Content-Type','text/plain');x.send(JSON.stringify({e:e,d:d,t:Date.now()-t0,ua:navigator.userAgent.slice(0,140)}))}catch(_){}}
b('head',{w:innerWidth,h:innerHeight,dpr:devicePixelRatio});
addEventListener('error',function(ev){b('error',{m:String(ev.message||ev.type),f:ev.filename,l:ev.lineno,tag:ev.target&&ev.target.tagName})},true);
addEventListener('unhandledrejection',function(ev){var r=ev.reason;b('reject',{m:String(r&&r.message||r)})});
document.addEventListener('DOMContentLoaded',function(){b('dom',{})});
addEventListener('load',function(){b('load',{})});
var n=0,iv=setInterval(function(){n++;var l=document.getElementById('loading');var st=document.getElementById('start');b('tick',{n:n,loadingShown:l?!(l.hidden||getComputedStyle(l).display==='none'):null,startShown:st?getComputedStyle(st).opacity:null,mem:(performance.memory&&performance.memory.usedJSHeapSize)||null});if(n>=16)clearInterval(iv)},2500);
addEventListener('pagehide',function(){b('pagehide',{})});})();</script>"""

with open(os.path.join(HERE, "index.html"), "rb") as f:
    RAW = f.read()
_i = RAW.find(b"<head>")
RAW = RAW[:_i + 6] + DIAG + RAW[_i + 6:] if _i >= 0 else DIAG + RAW
GZ = gzip.compress(RAW, 6)

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=HERE, **k)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            gz = "gzip" in self.headers.get("Accept-Encoding", "")
            body = GZ if gz else RAW
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            if gz:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            ua = self.headers.get("User-Agent", "")[:90]
            log("%s GET %s start %d bytes%s | %s" % (self.client_address[0], path, len(body), " gzip" if gz else "", ua))
            try:
                self.wfile.write(body)
                log("%s GET %s sent in full" % (self.client_address[0], path))
            except (BrokenPipeError, ConnectionResetError):
                log("%s GET %s phone cut the download short" % (self.client_address[0], path))
            return
        log("%s GET %s" % (self.client_address[0], path))
        try:
            super().do_GET()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        data = self.rfile.read(min(n, 20000)).decode("utf-8", "replace")
        if self.path.startswith("/beacon"):
            log("%s PHONE %s" % (self.client_address[0], data))
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *args):
        if "/beacon" in (fmt % args):
            return
        sys.stderr.write("  %s  %s\n" % (self.address_string(), fmt % args))

class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

def wifi_ip():
    """On a Mac, the address of the Wi-Fi interface itself (not a VPN tunnel)."""
    import subprocess
    devs = []
    try:
        out = subprocess.run(["networksetup", "-listallhardwareports"], capture_output=True, text=True, timeout=5).stdout
        port = None
        for line in out.splitlines():
            if line.startswith("Hardware Port:"):
                port = line.split(":", 1)[1].strip()
            elif line.startswith("Device:") and port and ("Wi-Fi" in port or "AirPort" in port):
                devs.append(line.split(":", 1)[1].strip())
    except Exception:
        pass
    for d in devs + ["en0", "en1"]:
        try:
            got = subprocess.run(["ipconfig", "getifaddr", d], capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            got = ""
        if got:
            return got, d
    return None, None

def all_ips():
    import subprocess
    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return ""
    res, iface = [], None
    for line in out.splitlines():
        if line and not line[0].isspace():
            iface = line.split(":", 1)[0]
        elif line.strip().startswith("inet ") and iface:
            res.append("%s=%s" % (iface, line.split()[1]))
    return " ".join(res)

route_ip = lan_ip()
wip, wdev = wifi_ip()
ip = wip or route_ip
log("addresses: wifi %s (%s), default route %s, all: %s" % (wip, wdev, route_ip, all_ips()))
if wip and route_ip and wip != route_ip:
    print("\nNote: a VPN or second network is active (%s). Phones will use the Wi-Fi address %s." % (route_ip, wip))
if not ip:
    print("\nCould not find this computer's wifi address. Are you connected to wifi?\n")
    sys.exit(1)

url = "http://%s:%d/" % (ip, PORT)
with open(os.path.join(HERE, "address.txt"), "w") as f:
    f.write(url + "\n")
slide = ""
try:
    with open(os.path.join(HERE, "slide-address.txt")) as f:
        slide = f.read().strip()
except OSError:
    pass
if slide and slide != url:
    print("\n" + "!" * 64)
    print("  Your laptop's wifi address changed since the QR on slide 9 was made.")
    print("  Slide QR points to: %s" % slide)
    print("  Phones need now:    %s" % url)
    print("  Show the QR page below instead, or ask Claude to refresh the slide QR.")
    print("!" * 64)
log("=== server started at %s ===" % url)
print("\nGlow Spa is live on this wifi.")
print("  Phones open:  %s" % url)
print("  QR page:      %sqr.html   (opening it in your browser now; put it on the big screen)" % url)
print("\nIf macOS asks whether Python can accept incoming connections, click Allow.")
print("Keep this window open during the meeting. Press Ctrl+C to stop.\n")

if not os.environ.get("NO_OPEN"):
    threading.Timer(1.0, lambda: webbrowser.open(url + "qr.html")).start()

try:
    Server(("0.0.0.0", PORT), Handler).serve_forever()
except KeyboardInterrupt:
    print("\nStopped.")
