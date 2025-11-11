#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import re
import socket
import sys
from flask import Flask, request, jsonify, Response

app = Flask(__name__)
# Resolve devices.json path for both normal and frozen (PyInstaller) modes
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(__file__)
DATA_FILE = os.path.join(BASE_DIR, 'devices.json')

# -------------------- Utils --------------------

def ensure_data_file():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False, indent=2)


def load_devices():
    ensure_data_file()
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def save_devices(devices):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(devices, f, ensure_ascii=False, indent=2)


def normalize_mac(mac: str) -> str:
    """Normalize MAC to colon-separated uppercase (e.g., AA:BB:CC:DD:EE:FF)."""
    if not isinstance(mac, str):
        return ''
    cleaned = re.sub(r'[^0-9A-Fa-f]', '', mac)
    if len(cleaned) != 12:
        return ''
    parts = [cleaned[i:i+2].upper() for i in range(0, 12, 2)]
    return ':'.join(parts)


def validate_mac(mac: str) -> bool:
    norm = normalize_mac(mac)
    return len(norm) == 17


def mac_to_bytes(mac: str) -> bytes:
    norm = normalize_mac(mac)
    if not norm:
        raise ValueError('Invalid MAC')
    return bytes(int(b, 16) for b in norm.split(':'))


def send_wol(mac: str, ip: str = '255.255.255.255', port: int = 9) -> None:
    """Send WOL magic packet to broadcast or directed address."""
    mac_bytes = mac_to_bytes(mac)
    magic_packet = b'\xff' * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(magic_packet, (ip, int(port)))


# -------------------- Routes --------------------

@app.route('/')
def index():
    html = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>WOL 唤醒工具</title>
  <style>
    :root { --bg:#0f172a; --panel:#111827; --text:#e5e7eb; --muted:#9ca3af; --primary:#22c55e; --danger:#ef4444; --border:#1f2937; --accent:#3b82f6; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif; background: var(--bg); color: var(--text); }
    header { padding: 24px; border-bottom: 1px solid var(--border); background: linear-gradient(180deg, rgba(59,130,246,0.25), rgba(34,197,94,0.2)); }
    header h1 { margin:0; font-size: 20px; }
    .container { max-width: 960px; margin: 24px auto; padding: 0 16px; }
    .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
    .row { display:flex; gap:12px; flex-wrap:wrap; }
    input, button { height: 36px; border-radius: 8px; border: 1px solid var(--border); background:#0b1220; color: var(--text); padding: 0 12px; }
    input::placeholder { color: var(--muted); }
    button { cursor:pointer; border: none; }
    button.primary { background: var(--primary); color: #041d12; font-weight: 600; }
    button.secondary { background: var(--accent); color: #05142e; font-weight: 600; }
    button.danger { background: var(--danger); color: #330b0b; font-weight: 600; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border-bottom: 1px solid var(--border); padding: 10px; text-align: left; }
    th { color: var(--muted); font-weight: 500; }
    .actions { display:flex; gap:8px; }
    .badge { display:inline-block; padding:2px 8px; border-radius:999px; border:1px solid var(--border); color: var(--muted); font-size:12px; }
    .footer { color: var(--muted); font-size: 12px; text-align:center; margin-top: 12px; }
    .checkbox { width: 18px; height: 18px; }
  </style>
</head>
<body>
  <header>
    <h1>WOL 唤醒工具</h1>
    <div class="badge">管理多台设备 · 支持搜索与批量唤醒</div>
  </header>
  <div class="container">
    <div class="panel">
      <div class="row" style="align-items:center">
        <input id="search" type="text" placeholder="搜索：MAC / 用户 IP / 备注" style="flex:1" />
        <button id="refresh" class="secondary">刷新</button>
        <button id="wakeSelected" class="primary">唤醒选中</button>
      </div>
    </div>

    <div class="panel">
      <div style="margin-bottom:8px; color:var(--muted)">添加设备（用户 IP 仅用于搜索；如需跨网段唤醒，可在最后配置广播 IP）</div>
      <div class="row">
        <input id="mac" type="text" placeholder="MAC 地址（AA:BB:CC:DD:EE:FF）" style="flex:1" />
        <input id="ip" type="text" placeholder="用户 IP（仅用于搜索，可选）" style="flex:1" />
        <input id="remark" type="text" placeholder="备注（可选）" style="flex:1" />
        <input id="broadcast_ip" type="text" placeholder="广播 IP（可选，用于跨网段唤醒）" style="flex:1" />
        <button id="add" class="primary">添加</button>
      </div>
    </div>

    <div class="panel">
      <table>
        <thead>
          <tr>
            <th style="width:40px"><input class="checkbox" type="checkbox" id="checkAll" /></th>
            <th>备注</th>
            <th>MAC 地址</th>
            <th>用户 IP</th>
            <th>广播 IP</th>
            <th style="width:220px">操作</th>
          </tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>

    <div class="footer">WOL XF · 端口默认 9</div>
  </div>

<script>
const api = {
  list: () => fetch('/api/devices').then(r=>r.json()),
  add: (d) => fetch('/api/devices', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(d)}).then(r=>r.json()),
  del: (mac) => fetch('/api/devices/' + encodeURIComponent(mac), {method:'DELETE'}).then(r=>r.json()),
  wake: (mac, port) => fetch('/api/wake', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({mac, port})}).then(r=>r.json()),
  search: (q) => fetch('/api/search?q=' + encodeURIComponent(q)).then(r=>r.json()),
};

let devices = [];
let filtered = [];

function render(list){
  const tbody = document.getElementById('tbody');
  tbody.innerHTML = '';
  list.forEach(d => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input class=\"checkbox\" type=\"checkbox\" data-mac=\"${d.mac}\" /></td>
      <td>${escapeHtml(d.remark || '')}</td>
      <td>${escapeHtml(d.mac)}</td>
      <td>${escapeHtml(d.ip || '')}</td>
      <td>${escapeHtml(d.broadcast_ip || '')}</td>
      <td class=\"actions\">
        <button class=\"secondary\" data-action=\"wake\" data-mac=\"${d.mac}\">唤醒</button>
        <button class=\"danger\" data-action=\"del\" data-mac=\"${d.mac}\">删除</button>
      </td>`;
    tbody.appendChild(tr);
  });
}

function escapeHtml(str){
  return String(str).replace(/[&<>\"]/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[s]));
}

async function refresh(){
  devices = await api.list();
  const q = document.getElementById('search').value.trim();
  if(q){ filtered = await api.search(q); } else { filtered = devices; }
  render(filtered);
}

function bindEvents(){
  document.getElementById('refresh').addEventListener('click', refresh);
  document.getElementById('add').addEventListener('click', async () => {
    const mac = document.getElementById('mac').value.trim();
    const ip = document.getElementById('ip').value.trim(); // 用户 IP，仅用于搜索
    const remark = document.getElementById('remark').value.trim();
    const broadcast_ip = document.getElementById('broadcast_ip').value.trim();
    if(!mac){ alert('请填写 MAC 地址'); return; }
    const res = await api.add({mac, ip: ip || undefined, remark: remark || undefined, broadcast_ip: broadcast_ip || undefined});
    if(res.error){ alert(res.error); } else {
      document.getElementById('mac').value='';
      document.getElementById('ip').value='';
      document.getElementById('remark').value='';
      document.getElementById('broadcast_ip').value='';
      refresh();
    }
  });
  document.getElementById('search').addEventListener('input', debounce(refresh, 200));
  document.getElementById('tbody').addEventListener('click', async (e) => {
    const btn = e.target.closest('button');
    if(!btn) return;
    const mac = btn.getAttribute('data-mac');
    const action = btn.getAttribute('data-action');
    if(action === 'wake'){
      const res = await api.wake(mac);
      if(res.error){ alert(res.error); } else { alert('唤醒数据包已发送'); }
    } else if(action === 'del'){
      if(confirm('确定删除该设备？')){
        const res = await api.del(mac);
        if(res.error){ alert(res.error); } else { refresh(); }
      }
    }
  });
  document.getElementById('checkAll').addEventListener('change', (e) => {
    document.querySelectorAll('#tbody .checkbox').forEach(chk => chk.checked = e.target.checked);
  });
  document.getElementById('wakeSelected').addEventListener('click', async () => {
    const chks = Array.from(document.querySelectorAll('#tbody .checkbox')).filter(c => c.checked);
    if(chks.length === 0){ alert('请先选择设备'); return; }
    for(const c of chks){
      const mac = c.getAttribute('data-mac');
      const res = await api.wake(mac);
      if(res.error){ alert('唤醒失败: ' + res.error); return; }
    }
    alert('已发送唤醒数据包（批量）');
  });
}

function debounce(fn, delay){
  let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn.apply(null, args), delay); };
}

(async function init(){ bindEvents(); await refresh(); })();
</script>
</body>
</html>'''
    return Response(html, mimetype='text/html')


@app.route('/api/devices', methods=['GET'])
def list_devices():
    devices = load_devices()
    return jsonify(devices)


@app.route('/api/devices', methods=['POST'])
def add_device():
    data = request.get_json(force=True) or {}
    mac = data.get('mac', '')
    ip = data.get('ip') or None  # 用户 IP，仅用于搜索
    remark = data.get('remark') or None
    broadcast_ip = data.get('broadcast_ip') or None

    if not validate_mac(mac):
        return jsonify({'error': 'MAC 地址格式不正确'}), 400

    mac_norm = normalize_mac(mac)
    devices = load_devices()
    if any(d.get('mac') == mac_norm for d in devices):
        return jsonify({'error': '该设备已存在'}), 400

    device = {'mac': mac_norm}
    if ip:
        device['ip'] = ip
    if remark:
        device['remark'] = remark
    if broadcast_ip:
        device['broadcast_ip'] = broadcast_ip

    devices.append(device)
    save_devices(devices)
    return jsonify({'ok': True, 'device': device})


@app.route('/api/devices/<mac>', methods=['DELETE'])
def delete_device(mac):
    mac_norm = normalize_mac(mac)
    devices = load_devices()
    new_devices = [d for d in devices if d.get('mac') != mac_norm]
    if len(new_devices) == len(devices):
        return jsonify({'error': '设备不存在'}), 404
    save_devices(new_devices)
    return jsonify({'ok': True})


@app.route('/api/search')
def search_devices():
    q = request.args.get('q', '').strip().lower()
    devices = load_devices()
    if not q:
        return jsonify(devices)
    def match(d):
        return any(
            q in str(d.get(k, '')).lower() for k in ['mac', 'ip', 'remark']
        )
    return jsonify([d for d in devices if match(d)])


@app.route('/api/wake', methods=['POST'])
def wake_device():
    data = request.get_json(force=True) or {}
    mac = data.get('mac', '')
    port = int(data.get('port') or 9)

    if not validate_mac(mac):
        return jsonify({'error': 'MAC 地址格式不正确'}), 400

    devices = load_devices()
    dev = next((d for d in devices if d.get('mac') == normalize_mac(mac)), None)
    # 如果配置了广播 IP，则使用；否则用全局广播 255.255.255.255
    broadcast_ip = dev.get('broadcast_ip') if dev and dev.get('broadcast_ip') else '255.255.255.255'
    try:
        send_wol(mac, ip=broadcast_ip, port=port)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '5050'))
    # When packaged as exe, run without debug reloader
    debug = not getattr(sys, 'frozen', False)
    app.run(host='0.0.0.0', port=port, debug=debug)