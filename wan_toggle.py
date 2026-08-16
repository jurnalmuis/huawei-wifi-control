import requests
from requests import PreparedRequest
import urllib3
import sys
import re
import time
import os
import base64

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".envhuawei")
DEBUG = "--debug" in sys.argv
DEBUG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug")


def load_env():
    cfg = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    return cfg


env = load_env()
MODEM_IP = env.get("MODEM_IP", "192.168.100.1")
BASE_URL = f"http://{MODEM_IP}"
USERNAME = env.get("MODEM_USER", "Support")
PASSWORD = env.get("MODEM_PASS", "telkom123")
WAN_IF = env.get("WAN_IF", "2_INTERNET_R_VID_200")
WAN_VID = env.get("WAN_VID", "200")

session = requests.Session()
session.verify = False
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
})


def debug_save(name, text):
    if not DEBUG:
        return
    os.makedirs(DEBUG_DIR, exist_ok=True)
    path = os.path.join(DEBUG_DIR, f"{name}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(text))
    print(f"  [D] Saved {path} ({len(str(text))} bytes)")


def login():
    print("[*] Login...")

    # Step 1: GET / to get login page
    resp = session.get(f"{BASE_URL}/", timeout=10, allow_redirects=True)
    debug_save("01_login_page", resp.text)
    print(f"  GET / -> {resp.status_code}, len={len(resp.text)}")

    if "txt_Username" not in resp.text:
        print("[!] Halaman login tidak ditemukan")
        return False

    # Step 2: CLEAR all cookies (JS behavior)
    session.cookies.clear()
    if DEBUG:
        print(f"  [D] Cookies cleared: {dict(session.cookies)}")

    # Step 3: POST /asp/GetRandCount.asp to get token
    token = ""
    try:
        resp_cnt = session.post(
            f"{BASE_URL}/asp/GetRandCount.asp",
            timeout=5,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        if DEBUG:
            print(f"  [D] GetRandCount headers resp: {dict(resp_cnt.headers)}")
        # Strip BOM and whitespace
        raw_token = resp_cnt.text
        token = raw_token.strip().lstrip("\ufeff").strip()
        debug_save("02_token_raw", repr(raw_token))
        debug_save("02_token_clean", token)
        print(f"  Token: {token[:20]}..." if len(token) > 20 else f"  Token: {token}")
    except Exception as e:
        print(f"  [!] GetRandCount error: {e}")

    if not token:
        print("[!] Token kosong")
        return False

    # Step 4: Ensure cookie jar is clean, we'll send Cookie header manually
    session.cookies.clear()

    # Step 5: POST /login.cgi with form data
    encoded_pass = base64.b64encode(PASSWORD.encode("utf-8")).decode("utf-8")

    data = {
        "UserName": USERNAME,
        "PassWord": encoded_pass,
        "Language": "english",
        "x.X_HW_Token": token,
    }

    if DEBUG:
        print(f"  [D] POST /login.cgi")
        print(f"      UserName={USERNAME}")
        print(f"      PassWord={encoded_pass} (raw: {PASSWORD})")
        print(f"      Language=english")
        print(f"      x.X_HW_Token={token}")

    try:
        # Use PreparedRequest to have full control over Cookie header
        pr = PreparedRequest()
        pr.prepare(
            method="POST",
            url=f"{BASE_URL}/login.cgi",
            data=data,
            headers={
                "User-Agent": session.headers.get("User-Agent", ""),
                "Cookie": "Cookie=body:Language:english:id=-1",
                "Referer": f"{BASE_URL}/",
            },
        )
        if DEBUG:
            print(f"  [D] Actual Cookie header: {pr.headers.get('Cookie', 'NONE')}")
            print(f"  [D] Actual Content-Type: {pr.headers.get('Content-Type', 'NONE')}")
            print(f"  [D] Body: {pr.body}")
        resp = session.send(pr, timeout=10, allow_redirects=False)
        debug_save("03_login_resp", resp.text)
        print(f"  POST /login.cgi -> {resp.status_code}, len={len(resp.text)}")

        if DEBUG:
            print(f"  [D] Response headers: {dict(resp.headers)}")

        # "Waiting..." page is the SUCCESS response
        if "Waiting" in resp.text or resp.status_code in (301, 302, 303):
            if resp.status_code in (301, 302, 303):
                location = resp.headers.get("Location", "/")
                print(f"  HTTP Redirect -> {location}")
            else:
                print(f"  Got 'Waiting...' page (login.cgi success), following JS redirect")

            # Check /index.asp for onttoken
            resp2 = session.get(f"{BASE_URL}/index.asp", timeout=10, allow_redirects=True)
            debug_save("04_after_login_index", resp2.text)
            print(f"  GET /index.asp -> {resp2.status_code}, len={len(resp2.text)}")

            if "onttoken" in resp2.text or "menuIframe" in resp2.text:
                print("[+] Login berhasil!")
                return True

            # Also try /html/bbsp/wan/wan.asp directly
            resp3 = session.get(f"{BASE_URL}/html/bbsp/wan/wan.asp", timeout=10, allow_redirects=True)
            if resp3.status_code == 200 and "onttoken" in resp3.text:
                print("[+] Login berhasil! (via wan.asp)")
                return True

            for check_resp in [resp2, resp3]:
                if "frame014" in check_resp.text:
                    print("[!] Username/Password salah (frame014)")
                    break
                elif "frame013" in check_resp.text:
                    print("[!] Terlalu banyak percobaan, terkunci (frame013)")
                    break
            else:
                print(f"[!] Login gagal - onttoken tidak ditemukan")
                if DEBUG:
                    print(f"  [D] Session cookies: {dict(session.cookies)}")

        else:
            print(f"[!] Unexpected response: {resp.status_code}")

    except Exception as e:
        print(f"  [!] Login error: {e}")

    print("[!] Login gagal")
    return False


def _decode_hex(s):
    return re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), s)


def extract_token(html):
    if not html:
        return ""
    m = re.search(r'id="onttoken"\s+value="([^"]+)"', html)
    if m:
        return m.group(1)
    m = re.search(r'id="hwonttoken"\s+value="([^"]+)"', html)
    if m:
        return m.group(1)
    return ""


def get_token():
    try:
        resp = session.get(f"{BASE_URL}/index.asp", timeout=5, allow_redirects=True)
        return extract_token(resp.text)
    except Exception:
        pass
    return ""


def get_wlan_token(band="2G"):
    """Token dari halaman WlanBasic.asp (persis yang dipakai browser utk set WLAN)."""
    try:
        url = f"{BASE_URL}/html/amp/wlanbasic/WlanBasic.asp"
        if band == "5G":
            url += "?5G"
        resp = session.get(url, timeout=10, allow_redirects=True)
        return extract_token(resp.text)
    except Exception:
        pass
    return ""


def get_wan_info():
    token = get_token()
    if not token:
        return None
    try:
        resp = session.post(
            f"{BASE_URL}/html/bbsp/common/getwanlist.asp",
            data=f"&x.X_HW_Token={token}",
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        debug_save("getwanlist", resp.text)
        for ctor in ['new WanPPP\\(([^)]+)\\)', 'new WanIP\\(([^)]+)\\)']:
            for m in re.finditer(ctor, resp.text):
                args = re.findall(r'"([^"]*)"', m.group(1))
                if not args or len(args) < 27:
                    continue
                domain = _decode_hex(args[0])
                enable = args[1]
                conn_status = _decode_hex(args[4]).title() if len(args) > 4 else ""
                ip_addr = _decode_hex(args[13]) if len(args) > 13 else ""
                gateway = _decode_hex(args[14]) if len(args) > 14 else ""
                vlan = _decode_hex(args[22]) if len(args) > 22 else ""
                service_list = _decode_hex(args[26]).upper() if len(args) > 26 else ""
                if vlan == WAN_VID and "INTERNET" in service_list:
                    return {
                        "domain": domain, "enable": enable,
                        "conn_status": conn_status, "ip": ip_addr,
                        "gateway": gateway, "vlan": vlan,
                        "service": service_list,
                    }
        for ctor in ['new WanPPP\\(([^)]+)\\)', 'new WanIP\\(([^)]+)\\)']:
            for m in re.finditer(ctor, resp.text):
                args = re.findall(r'"([^"]*)"', m.group(1))
                if not args or len(args) < 23:
                    continue
                domain = _decode_hex(args[0])
                vlan = _decode_hex(args[22]) if len(args) > 22 else ""
                if vlan == WAN_VID:
                    return {
                        "domain": domain, "enable": args[1],
                        "conn_status": _decode_hex(args[4]).title() if len(args) > 4 else "",
                        "ip": _decode_hex(args[13]) if len(args) > 13 else "",
                        "gateway": _decode_hex(args[14]) if len(args) > 14 else "",
                        "vlan": vlan,
                        "service": _decode_hex(args[7]).upper() if len(args) > 7 else "",
                    }
    except Exception as e:
        if DEBUG:
            print(f"  [D] getwanlist error: {e}")
    return None


def get_public_ip():
    """Cek IP publik dari komputer (di belakang NAT modem) via layanan eksternal."""
    for url in ("https://api.ipify.org", "https://icanhazip.com", "https://ifconfig.me/ip"):
        try:
            resp = requests.get(url, timeout=5, verify=False)
            ip = resp.text.strip()
            if ip and ip.count(".") == 3 and all(p.isdigit() for p in ip.split(".")):
                return ip
        except Exception:
            continue
    return ""


def print_wan_info(info):
    if not info:
        print("  Status: Tidak diketahui")
        return
    print(f"  Domain: {info['domain']}")
    print(f"  Service: {info['service']}")
    print(f"  VLAN: {info['vlan']}")
    print(f"  IP: {info['ip']}")
    print(f"  Gateway: {info['gateway']}")
    print(f"  Koneksi: {info['conn_status']}")
    if info["enable"] == "1":
        print("  Status: ENABLED (ON)")
    else:
        print("  Status: DISABLED (OFF)")
    pub = get_public_ip()
    if pub:
        print(f"  IP Publik: {pub}")
    else:
        print("  IP Publik: (tidak dapat dicek)")


# ================= WLAN =================

WLAN_2G_DOMAIN = "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1"
WLAN_5G_DOMAIN = "InternetGatewayDevice.LANDevice.1.WLANConfiguration.5"
WLAN_BASIC_PAGE = "/html/amp/wlanbasic/WlanBasic.asp"

CHANNEL_WIDTH = {
    "0": "Auto 20/40 MHz", "1": "20 MHz", "2": "40 MHz",
    "3": "Auto 20/40/80 MHz",
}


def wlan_domain(band):
    return WLAN_5G_DOMAIN if band == "5G" else WLAN_2G_DOMAIN


def extract_js_objects(html, pattern):
    out = []
    for m in re.finditer(pattern, html):
        out.append(re.findall(r'"([^"]*)"', m.group(1)))
    return out


def get_wlan_list(band="2G", html=None):
    """Enumerate SEMUA SSID pada band tsb (bisa lebih dari satu).
    Band ditentukan dari LowerLayers (index 23 stWlan): Radio.1 = 2G, Radio.2 = 5G."""
    if html is None:
        url = f"{BASE_URL}{WLAN_BASIC_PAGE}"
        if band == "5G":
            url += "?5G"
        try:
            resp = session.get(url, timeout=10, allow_redirects=True)
        except Exception as e:
            if DEBUG:
                print(f"  [D] WLAN {band} fetch error: {e}")
            return []
        debug_save(f"wlan_basic_{band}", resp.text)
        html = resp.text
    if "stWlanWifi" not in html:
        return []

    radio = "Radio.2" if band == "5G" else "Radio.1"
    items = []
    wifi_map = {}
    for args in extract_js_objects(html, r"new stWlanWifi\(([^)]+)\)"):
        if len(args) >= 10:
            wifi_map[_decode_hex(args[0])] = args

    for args in extract_js_objects(html, r"new stWlan\(([^)]+)\)"):
        if len(args) < 24:
            continue
        wdomain = _decode_hex(args[0])
        lower = _decode_hex(args[23])
        if radio not in lower:
            continue
        info = {
            "band": band,
            "domain": wdomain,
            "enable": args[2],
            "ssid": _decode_hex(args[3]),
            "broadcast": args[4],
            "devices": args[5],
            "wmm": args[6],
            "beacon": _decode_hex(args[7]),
            "auth": _decode_hex(args[17]),
            "encryption": _decode_hex(args[16]),
        }
        wf = wifi_map.get(wdomain)
        if wf:
            info.update({
                "name": _decode_hex(wf[1]),
                "mode": _decode_hex(wf[4]),
                "channel": _decode_hex(wf[5]),
                "power": _decode_hex(wf[6]),
                "auto_channel": wf[8],
                "width": wf[9],
            })
        for pargs in extract_js_objects(html, r"new stPreSharedKey\(([^)]+)\)"):
            if pargs and _decode_hex(pargs[0]).startswith(wdomain):
                info["psk"] = _decode_hex(pargs[1]) if len(pargs) > 1 else "********"
                break
        items.append(info)
    return items


def get_wlan_info(band="2G", domain=None):
    """Info WLAN. domain=None -> pakai default per band (SSID utama)."""
    items = get_wlan_list(band)
    if not items:
        return None
    if domain:
        for it in items:
            if it["domain"] == domain:
                return it
        return None
    default = wlan_domain(band)
    for it in items:
        if it["domain"] == default:
            return it
    return items[0]


def print_wlan_info(info):
    if not info or "ssid" not in info:
        print("  Status: tidak ditemukan (band nonaktif?)")
        return
    print(f"  SSID       : {info['ssid']}")
    print(f"  Status     : {'ON' if info.get('enable') == '1' else 'OFF'}")
    print(f"  Broadcast  : {'ON' if info.get('broadcast') == '1' else 'OFF'}")
    print(f"  Max Device : {info.get('devices', '-')}")
    ch = info.get("channel", "?")
    ch_show = f"{ch} (Automatic)" if ch in ("0", "-1") else ch
    print(f"  Channel    : {ch_show}")
    width_val = info.get("width", "")
    print(f"  Channel W  : {CHANNEL_WIDTH.get(width_val, width_val or '-')}")
    print(f"  TX Power   : {info.get('power', '-')}%")
    print(f"  Mode       : {info.get('mode', '-')}")
    print(f"  Password   : {info.get('psk') or '********'}")


def show_wlan_status():
    print("\n" + "=" * 85)
    print("  STATUS WLAN")
    print("=" * 85)
    wlan_2g = get_wlan_info("2G")
    wlan_5g = get_wlan_info("5G")

    def val(d, k, fmt=None):
        if not d or k not in d:
            return "-"
        v = d[k]
        return fmt(v) if fmt else v

    def wfmt(v): return CHANNEL_WIDTH.get(v, v)

    def chfmt(v):
        if v in ("0", "-1"): return f"{v} (Automatic)"
        return v

    rows = [
        ("SSID",            lambda d: val(d, "ssid")),
        ("Status",          lambda d: "ON" if val(d, "enable") == "1" else "OFF"),
        ("Broadcast",       lambda d: "ON" if val(d, "broadcast") == "1" else "OFF"),
        ("Max Device",      lambda d: val(d, "devices")),
        ("Channel",         lambda d: chfmt(val(d, "channel"))),
        ("Channel Width",   lambda d: wfmt(val(d, "width"))),
        ("TX Power",        lambda d: val(d, "power") + "%"),
        ("Mode",            lambda d: val(d, "mode")),
        ("Password",        lambda d: val(d, "psk") or "********"),
    ]

    header = f"{'Parameter':<16}  {'2.4G':<32}  {'5G':<32}"
    print(header)
    print("-" * len(header))
    for label, fn in rows:
        v2 = fn(wlan_2g)
        v5 = fn(wlan_5g)
        print(f"{label:<16}  {str(v2):<32}  {str(v5):<32}")
    print("=" * 85 + "\n")


# ================= WLAN SET (REAL) =================

def _get_wlan_info_retry(band, tries=6, delay=4, domain=None):
    """get_wlan_info dengan retry — radio 5G sempat unreachable sesaat setelah restart."""
    for i in range(tries):
        info = get_wlan_info(band, domain=domain)
        if info:
            return info
        time.sleep(delay)
    return None


def _wait_for_ssid_proc(band, max_retries=10, delay=3):
    """Tunggu hingga proses SSID selesai (POST getSsidProcFlag.asp, sesuai JS asli)"""
    wlanid = 5 if band == "5G" else 1
    for attempt in range(max_retries):
        try:
            resp = session.post(
                f"{BASE_URL}/html/amp/common/getSsidProcFlag.asp?&1=1",
                data=f"wlanid={wlanid}",
                timeout=5,
            )
            text = resp.text.strip()
            if DEBUG:
                print(f"  [D] Attempt {attempt+1}: proc flag = {text}, waiting...")
            if text == "0":
                return True
            time.sleep(delay)
        except Exception as e:
            if DEBUG:
                print(f"  [D] Proc flag check error: {e}")
            time.sleep(delay)
    return False


def set_wlan_fields(band, fields, key_value=None, request_file="html/amp/wlanbasic/WlanBasic.asp", check_proc=True, ssid_domain=None):
    """Set field WLAN — pola PERSIS request browser (tertangkap via Playwright):
    POST /html/amp/wlanbasic/set.cgi?w=...WifiCoverSetWlanBasic&y=<domain>&z=<domain>.WPS&k=<domain>.PreSharedKey.1
    Body: y.* (WLANConfiguration) + z.* (WPS) + w.* (WifiCover) + x.X_HW_Token.
    Field w.* WAJIB lengkap, kalau tidak ErrCode 0x1.
    ssid_domain: domain WLANConfiguration spesifik (utk multi-SSID); None = default per band."""
    token = get_wlan_token(band)
    if not token:
        token = get_token()
    if not token:
        print("  [!] Token tidak ditemukan")
        return False
    domain = ssid_domain or wlan_domain(band)
    info = get_wlan_info(band, domain=domain)
    m_inst = re.search(r"WLANConfiguration\.(\d+)$", domain)
    ssid_inst = m_inst.group(1) if m_inst else ("5" if band == "5G" else "1")
    enable = info.get("enable", "1") if info else "1"
    ssid = info.get("ssid", "") if info else ""
    broadcast = info.get("broadcast", "1") if info else "1"
    devices = info.get("devices", "10") if info else "10"
    wmm = info.get("wmm", "1") if info else "1"
    mode = info.get("mode", "11bgn") if info else "11bgn"
    beacon = info.get("beacon", "WPAand11i") if info else "WPAand11i"
    auth = info.get("auth", "PSKAuthentication") if info else "PSKAuthentication"
    encr = info.get("encryption", "TKIPandAESEncryption") if info else "TKIPandAESEncryption"

    url = (f"{BASE_URL}/html/amp/wlanbasic/set.cgi"
           f"?w=InternetGatewayDevice.X_HW_DEBUG.AMP.WifiCoverSetWlanBasic"
           f"&y={domain}"
           f"&z={domain}.WPS"
           f"&k={domain}.PreSharedKey.1"
           f"&RequestFile={request_file}")

    body = {
        # addParameter1 -> y.*
        "y.Enable": enable,
        "y.SSIDAdvertisementEnabled": broadcast,
        "y.SSID": ssid,
        "y.X_HW_AssociateNum": devices,
        "y.BeaconType": beacon,
        "y.X_HW_WPAand11iAuthenticationMode": auth,
        "y.X_HW_WPAand11iEncryptionModes": encr,
        "y.X_HW_GroupRekey": "3600",
        # WPS -> z.*
        "z.Enable": "0",
        "z.X_HW_ConfigMethod": "PushButton",
        # WifiCover -> w.*
        "w.SsidInst": ssid_inst,
        "w.SSID": ssid,
        "w.Enable": enable,
        "w.Standard": mode,
        "w.BasicAuthenticationMode": "None",
        "w.BasicEncryptionModes": encr,
        "w.WPAAuthenticationMode": "EAPAuthentication",
        "w.WPAEncryptionModes": encr,
        "w.IEEE11iAuthenticationMode": "EAPAuthentication",
        "w.IEEE11iEncryptionModes": encr,
        "w.MixAuthenticationMode": auth,
        "w.MixEncryptionModes": encr,
        "w.SSIDAdvertisementEnabled": broadcast,
        "w.WMMEnable": wmm,
        "w.MaxAssociateNum": devices,
        "w.BeaconType": beacon,
        "w.WEPEncryptionLevel": "104-bit",
        "w.WEPKeyIndex": "1",
        # token
        "x.X_HW_Token": token,
    }
    # terapkan field yang diminta (ubah SSID/Enable dsb di kedua prefix y dan w)
    for k, v in fields.items():
        if f"y.{k}" in body:
            body[f"y.{k}"] = v
        body[f"w.{k}"] = v
    if key_value is not None:
        body["w.Key"] = key_value
    # token harus param TERAKHIR agar request diterima (sesuai urutan browser)
    body["x.X_HW_Token"] = body.pop("x.X_HW_Token")
    referer = f"{BASE_URL}/html/amp/wlanbasic/WlanBasic.asp"
    if band == "5G":
        referer += "?5G"
    else:
        referer += "?2G"
    try:
        resp = session.post(url, data=body, timeout=30, headers={
            "Referer": referer,
            "Origin": BASE_URL,
            "Content-Type": "application/x-www-form-urlencoded",
        })
    except Exception as e:
        print(f"  [!] set error: {e} (sinyal: radio {band} restart. Verifikasi ulang...)")
        # 5G: koneksi bisa diputus saat radio restart padahal perubahan sudah diterapkan.
        check = _get_wlan_info_retry(band, domain=domain)
        if check:
            info_key = {
                "SSID": "ssid",
                "Enable": "enable",
                "SSIDAdvertisementEnabled": "broadcast",
                "WMMEnable": "wmm",
                "X_HW_AssociateNum": "devices",
            }
            ok = all(str(check.get(info_key.get(k, k))) == str(v) for k, v in fields.items())
            if ok:
                print(f"  [?] Set terlanjur diterapkan (verifikasi cocok) — dianggap berhasil")
                return True
            print(f"  [!] Verifikasi gagal: fields yang diminta tidak cocok dengan nilai saat ini")
        return False
    debug_save(f"set_wlan_{band}", resp.text)
    if resp.status_code == 200 and "ErrCode" not in resp.text:
        if check_proc:
            print("  [>] Menunggu proses SSID selesai...")
            if _wait_for_ssid_proc(band):
                print("  [+] Proses SSID selesai!")
                return True
            else:
                print("  [!] Timeout menunggu proses SSID")
                return False
        return True
    err = re.search(r'ErrCode\s*=\s*"([^"]+)"', resp.text)
    if err:
        print(f"  [!] Error: {err.group(1)}")
    else:
        print(f"  [!] Gagal (HTTP {resp.status_code})")
    return False


def set_wlan_ssid(band, ssid, ssid_domain=None):
    info = get_wlan_info(band, domain=ssid_domain)
    fields = {"SSID": ssid}
    if info:
        fields.setdefault("Enable", info.get("enable", "1"))
        fields.setdefault("SSIDAdvertisementEnabled", info.get("broadcast", "1"))
        fields.setdefault("WMMEnable", info.get("wmm", "1"))
    if set_wlan_fields(band, fields, ssid_domain=ssid_domain):
        print(f"[+] SSID {band} diganti -> {ssid}")
        return True
    print("[!] Ganti SSID gagal")
    return False


def set_wlan_password(band, password, ssid_domain=None):
    """Ganti password WLAN. Browser hanya menambah param 'w.Key' (tanpa field auth tambahan)."""
    if set_wlan_fields(band, {}, key_value=password, ssid_domain=ssid_domain):
        print(f"[+] Password {band} diganti")
        return True
    print("[!] Ganti password gagal")
    return False


def set_wlan_enable(band, enable, ssid_domain=None):
    action = "ENABLE" if enable else "DISABLE"
    if set_wlan_fields(band, {"Enable": "1" if enable else "0"}, ssid_domain=ssid_domain):
        print(f"[+] WLAN {band} {action} berhasil")
        return True
    print(f"[!] WLAN {band} {action} gagal")
    return False


def set_wlan_adv(band, key, value, ssid_domain=None):
    """Set parameter advanced (Channel/TransmitPower/X_HW_HT20/X_HW_Standard).

    Meniru halaman WlanAdvance.asp: endpoint set.cgi?x=<domain>.X_HW_AdvanceConf
    &y=<domain>&r=<Radio domain> (5G menambah z=WiFi.X_HW_GlobalConfig).
    Body: y.* (WLANConfiguration) + x.* (DtimPeriod/BeaconPeriod/RTS/Frag)
    + x.X_HW_Token param terakhir. Semua nilai advance dikirim (current + yang diganti).
    """
    domain = ssid_domain or wlan_domain(band)
    info = get_wlan_info(band, domain=domain)
    if not info:
        print(f"  [!] Info WLAN {band} tidak didapat")
        return False
    radio_domain = (
        "InternetGatewayDevice.LANDevice.1.WiFi.Radio.2" if band == "5G"
        else "InternetGatewayDevice.LANDevice.1.WiFi.Radio.1")
    global_domain = "InternetGatewayDevice.LANDevice.1.WiFi.X_HW_GlobalConfig"

    token = ""
    try:
        page_url = f"{BASE_URL}/html/amp/wlanadvance/wlanadvance.asp"
        if band == "5G":
            page_url += "?5G"
        resp = session.get(page_url, timeout=10, allow_redirects=True)
        token = extract_token(resp.text)
    except Exception:
        pass
    if not token:
        token = get_token()
    if not token:
        print("  [!] Token tidak ditemukan")
        return False

    cur_channel = info.get("channel", "0")
    cur_width = info.get("width", "2" if band == "2G" else "3")
    cur_power = info.get("power", "100")
    cur_mode = info.get("mode", "11bgn" if band == "2G" else "11ac")

    if key == "Channel":
        if value in ("0", "-1"):
            y_channel, auto = "0", "1"
        else:
            y_channel, auto = value, "0"
    else:
        y_channel = cur_channel
        auto = info.get("auto_channel", "0")
    y_width = value if key == "X_HW_HT20" else cur_width
    y_power = value if key == "TransmitPower" else cur_power
    y_mode = value if key == "X_HW_Standard" else cur_mode

    if band == "5G":
        url = (f"{BASE_URL}/html/amp/wlanadvance/set.cgi"
               f"?z={global_domain}"
               f"&x={domain}.X_HW_AdvanceConf"
               f"&y={domain}"
               f"&r={radio_domain}"
               f"&RequestFile=html/amp/wlanadv/WlanAdvance.asp")
    else:
        url = (f"{BASE_URL}/html/amp/wlanadvance/set.cgi"
               f"?x={domain}.X_HW_AdvanceConf"
               f"&y={domain}"
               f"&r={radio_domain}"
               f"&RequestFile=html/amp/wlanadv/WlanAdvance.asp")

    body = {
        "y.Channel": y_channel,
        "y.AutoChannelEnable": auto,
        "y.X_HW_HT20": y_width,
        "y.TransmitPower": y_power,
        "y.X_HW_Standard": y_mode,
        "x.DtimPeriod": "1",
        "x.BeaconPeriod": "100",
        "x.RTSThreshold": "2346",
        "x.FragThreshold": "2346",
        "x.X_HW_Token": token,
    }

    referer = f"{BASE_URL}/html/amp/wlanadvance/wlanadvance.asp"
    if band == "5G":
        referer += "?5G"
    else:
        referer += "?2G"
    try:
        resp = session.post(url, data=body, timeout=30, headers={
            "Referer": referer,
            "Origin": BASE_URL,
            "Content-Type": "application/x-www-form-urlencoded",
        })
    except Exception as e:
        print(f"  [!] set error: {e} (radio {band} restart?). Verifikasi ulang...")
        check = _get_wlan_info_retry(band, domain=domain)
        if check:
            info_key = {
                "Channel": "channel",
                "TransmitPower": "power",
                "X_HW_HT20": "width",
                "X_HW_Standard": "mode",
            }
            ok = str(check.get(info_key.get(key, key))) == str(value)
            if ok:
                print("  [?] Set terlanjur diterapkan (verifikasi cocok) — dianggap berhasil")
                return True
            print("  [!] Verifikasi gagal: nilai tidak cocok dengan yang diminta")
        return False
    debug_save(f"set_wlan_adv_{band}", resp.text)
    if resp.status_code == 200 and "ErrCode" not in resp.text:
        print(f"[+] WLAN {band} {key}={value} berhasil")
        return True
    err = re.search(r'ErrCode\s*=\s*"([^"]+)"', resp.text)
    if err:
        print(f"  [!] Error: {err.group(1)}")
    else:
        print(f"  [!] Gagal (HTTP {resp.status_code})")
    return False


# ================= MENU =================

def get_available_channels(band, mode=None, width=None, country="ID"):
    """Ambil daftar channel tersedia dari modem (endpoint yang sama dengan browser:
    ../common/WlanChannel.asp POST freq/country/standard/width)."""
    freq = "2G" if band == "2G" else "5G"
    if mode is None:
        mode = "11bgn" if band == "2G" else "11ac"
    if width is None:
        width = "2" if band == "2G" else "3"
    try:
        resp = session.post(
            f"{BASE_URL}/html/amp/common/WlanChannel.asp?&1=1",
            data=f"freq={freq}&country={country}&standard={mode}&width={width}",
            timeout=10,
        )
        text = resp.text.strip()
    except Exception as e:
        if DEBUG:
            print(f"  [D] WlanChannel error: {e}")
        return []
    channels = [c for c in text.replace("\r", "").split(",") if c.strip().isdigit()]
    return channels

def wlan_pick_band():
    print("  1 = 2.4G   2 = 5G")
    p = input("Band [1]: ").strip()
    return "5G" if p == "2" else "2G"


def wlan_pick_ssid(band):
    """Tampilkan daftar SSID pada band, user pilih. return (domain, info) atau (None, None)."""
    items = get_wlan_list(band)
    if not items:
        print("  [!] Tidak ada SSID pada band ini")
        return None, None
    print(f"\n  SSID di {band}:")
    for i, it in enumerate(items, 1):
        st = 'ON' if it.get('enable') == '1' else 'OFF'
        print(f"   {i}. {it['ssid']:<32} [{st}]")
    p = input(f"Pilih SSID [1]: ").strip()
    if not p:
        p = "1"
    try:
        idx = int(p) - 1
        if 0 <= idx < len(items):
            return items[idx]["domain"], items[idx]
    except ValueError:
        pass
    print("  [!] Pilihan tidak valid")
    return None, None


def wlan_set_ssid_menu():
    band = wlan_pick_band()
    domain, info = wlan_pick_ssid(band)
    if not info:
        return
    print(f"\n  SSID saat ini  : {info['ssid']}")
    print(f"  Status       : {'ON' if info.get('enable') == '1' else 'OFF'}")
    ssid = input("SSID baru (kosong = batal): ").strip()
    if not ssid:
        print("[*] Dibatalkan")
        return
    if len(ssid) > 32:
        print("[!] SSID maksimal 32 karakter")
        return
    set_wlan_ssid(band, ssid, ssid_domain=domain)


def wlan_set_password_menu():
    band = wlan_pick_band()
    domain, info = wlan_pick_ssid(band)
    if not info:
        return
    print(f"\n  SSID saat ini  : {info['ssid']}")
    print(f"  Status       : {'ON' if info.get('enable') == '1' else 'OFF'}")
    pwd = input("Password baru 8-63 karakter (kosong = batal): ").strip()
    if not pwd:
        print("[*] Dibatalkan")
        return
    if not (8 <= len(pwd) <= 63):
        print("[!] Password harus 8-63 karakter")
        return
    pwd2 = input("Ulangi password (kosong = batal): ").strip()
    if not pwd2:
        print("[*] Dibatalkan")
        return
    if pwd != pwd2:
        print("[!] Password tidak sama")
        return
    set_wlan_password(band, pwd, ssid_domain=domain)


def wlan_toggle_menu():
    band = wlan_pick_band()
    domain, info = wlan_pick_ssid(band)
    if not info:
        return
    cur = info.get("enable")
    print(f"  Status saat ini: {'ON' if cur == '1' else 'OFF' if cur == '0' else 'tidak diketahui'}")
    aksi = input("1 = ON, 2 = OFF, Enter = batal: ").strip()
    if aksi == "1":
        set_wlan_enable(band, True, ssid_domain=domain)
    elif aksi == "2":
        set_wlan_enable(band, False, ssid_domain=domain)
    else:
        print("[*] Dibatalkan")


def wlan_adv_menu():
    band = wlan_pick_band()
    items = get_wlan_list(band)
    if not items:
        print("  [!] Tidak ada SSID pada band ini")
        return
    info = items[0]
    domain = info["domain"]
    names = ", ".join(it["ssid"] for it in items)
    print(f"  SSID ({band}): {names}")
    print("  1 = Channel       2 = TX Power")
    print("  3 = Channel Width  4 = Mode")
    p = input("Pilihan (Enter = batal): ").strip()
    if not p:
        print("[*] Dibatalkan")
        return
    if p == "1":
        chans = get_available_channels(band)
        cur = info.get("channel") if info else ""
        print("  Channel tersedia:")
        for i, ch in enumerate(chans, 1):
            mark = f"  <-- saat ini" if ch == cur else ""
            print(f"   {i}. {ch}{mark}")
        print("   0. Auto")
        v = input("Pilih channel (kosong = batal): ").strip()
        if not v:
            print("[*] Dibatalkan")
            return
        if v == "0":
            set_wlan_adv(band, "Channel", "0", ssid_domain=domain)
            return
        try:
            idx = int(v) - 1
            if 0 <= idx < len(chans):
                set_wlan_adv(band, "Channel", chans[idx], ssid_domain=domain)
                return
        except ValueError:
            pass
        print("[!] Pilihan tidak valid")
    elif p == "2":
        v = input("TX Power % (20/40/60/80/100, kosong = batal): ").strip()
        if not v:
            print("[*] Dibatalkan")
            return
        set_wlan_adv(band, "TransmitPower", v, ssid_domain=domain)
    elif p == "3":
        if band == "2G":
            print("  0 = Auto 20/40 MHz   1 = 20 MHz   2 = 40 MHz")
        else:
            print("  0 = Auto 20/40 MHz   1 = 20 MHz   2 = 40 MHz   3 = Auto 20/40/80 MHz")
        v = input("Width (kosong = batal): ").strip()
        if not v:
            print("[*] Dibatalkan")
            return
        if band == "2G" and v not in ("0", "1", "2"):
            print("[!] Pilihan tidak valid untuk 2.4G")
            return
        if band == "5G" and v not in ("0", "1", "2", "3"):
            print("[!] Pilihan tidak valid untuk 5G")
            return
        set_wlan_adv(band, "X_HW_HT20", v, ssid_domain=domain)
    elif p == "4":
        v = input("Mode (kosong = batal): ").strip()
        if not v:
            print("[*] Dibatalkan")
            return
        set_wlan_adv(band, "X_HW_Standard", v, ssid_domain=domain)
    else:
        print("[!] Pilihan tidak valid")


# ================= WAN =================

def set_wan_enable(enable=True):
    token = get_token()
    if not token:
        print("[!] Token tidak ditemukan")
        return False
    val = "1" if enable else "0"
    action = "ENABLE" if enable else "DISABLE"

    info = get_wan_info()
    if not info:
        print(f"[!] WAN domain tidak ditemukan")
        return False

    data = f"GROUP_a_y.Enable={val}&x.X_HW_Token={token}"
    resp = session.post(
        f"{BASE_URL}/set.cgi?GROUP_a_y={info['domain']}&RequestFile=html/bbsp/wan/wan.asp",
        data=data, timeout=10,
    )
    debug_save(f"set_{action}", resp.text)

    if resp.status_code == 200 and "ErrCode" not in resp.text:
        print(f"[+] WAN {action} berhasil")
        return True
    err_match = re.search(r'ErrCode\s*=\s*"([^"]+)"', resp.text)
    if err_match:
        print(f"[!] WAN {action} error: {err_match.group(1)}")
    else:
        print(f"[!] WAN {action} gagal (HTTP {resp.status_code})")
    return False


def auto_toggle():
    print("\n[*] AUTO TOGGLE: DISABLE -> 2s -> ENABLE")
    try:
        print("[1] DISABLE...")
        set_wan_enable(False)
        time.sleep(2)
        print("[2] ENABLE...")
        set_wan_enable(True)
        time.sleep(2)
    except KeyboardInterrupt:
        print("\n[*] Stopped")
        return
    print("[*] Selesai")


def restart_modem():
    token = get_token()
    if not token:
        print("[!] Token tidak ditemukan")
        return False

    print("[*] Restart modem...")
    try:
        resp = session.post(
            f"{BASE_URL}/set.cgi?x=InternetGatewayDevice.X_HW_DEBUG.SMP.DM.ResetBoard&RequestFile=CustomApp/mainpage.asp",
            data=f"x.X_HW_Token={token}",
            timeout=10,
            allow_redirects=False,
        )
        debug_save("restart_modem", resp.text)
        if resp.status_code == 200 and "ErrCode" not in resp.text:
            print("[+] Modem sedang restart, tunggu 30-60 detik...")
            return True
        em = re.search(r'ErrCode\s*=\s*"([^"]+)"', resp.text)
        err_code = em.group(1) if em else "NONE"
        print(f"[!] Restart gagal (HTTP {resp.status_code}, ErrCode={err_code})")
    except requests.exceptions.Timeout:
        print("[+] Modem sedang restart (timeout = sukses), tunggu 30-60 detik...")
        return True
    except Exception as e:
        print(f"[!] Restart error: {e}")
    return False


def show_status():
    print("\n" + "=" * 45)
    print("  MODEM: Huawei HG8245W5-6T")
    print(f"  WAN IF: {WAN_IF}")
    print("=" * 45)
    print_wan_info(get_wan_info())
    print("=" * 45 + "\n")


def ensure_login():
    info = get_wan_info()
    if info is not None:
        return True
    print("[*] Session habis, login ulang...")
    return login()


def main():
    print("\n" + "=" * 45)
    print("  HUAWEI WAN TOGGLE - HG8245W5-6T")
    print(f"  IP: {MODEM_IP} | WAN: {WAN_IF}")
    if DEBUG:
        print("  MODE: DEBUG")
    print("=" * 45)

    if not login():
        print("[!] Tidak bisa login, exit")
        sys.exit(1)

    while True:
        print("\n[1] Cek Status WAN")
        print("[2] Auto Restart WAN")
        print("[3] Restart Modem")
        print("[4] Cek Status WLAN (2.4G & 5G)")
        print("[5] WLAN: Ganti SSID")
        print("[6] WLAN: Ganti Password")
        print("[7] WLAN: On / Off")
        print("[8] WLAN: Channel & TX Power")
        print("[0] Keluar")
        choice = input("\nPilihan: ").strip()

        if choice == "1":
            if ensure_login():
                show_status()
        elif choice == "2":
            if ensure_login():
                auto_toggle()
                print("[*] Menunggu koneksi stabil (2 detik)...")
                time.sleep(2)
                show_status()
        elif choice == "3":
            if ensure_login():
                confirm = input("Restart modem? (y/n): ").strip().lower()
                if confirm in ("y", "yes"):
                    restart_modem()
                else:
                    print("[*] Dibatalkan")
        elif choice == "4":
            if ensure_login():
                show_wlan_status()
        elif choice == "5":
            if ensure_login():
                wlan_set_ssid_menu()
        elif choice == "6":
            if ensure_login():
                wlan_set_password_menu()
        elif choice == "7":
            if ensure_login():
                wlan_toggle_menu()
        elif choice == "8":
            if ensure_login():
                wlan_adv_menu()
        elif choice == "0":
            break


if __name__ == "__main__":
    main()