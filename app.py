#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import re
import socket
import sys
import time
import logging
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify, Response
from logging.handlers import RotatingFileHandler

app = Flask(__name__)

# Resolve paths for both normal and frozen (PyInstaller) modes
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(__file__)

DATA_FILE = os.path.join(BASE_DIR, 'devices.json')
LOG_FILE = os.path.join(BASE_DIR, 'wol.log')

# Setup logging
def setup_logging():
    logger = logging.getLogger('WOL')
    logger.setLevel(logging.INFO)
    
    # Rotating file handler (max 5MB, keep 3 backups)
    handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)
    
    return logger

logger = setup_logging()

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
    logger.info(f'发送WOL数据包: MAC={mac}, IP={ip}, Port={port}')


def check_port(ip: str, port: int = 3389, timeout: float = 1.0) -> dict:
    """Check if a port is open and measure latency."""
    if not ip:
        return {'online': False, 'latency': None}
    
    try:
        start_time = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        
        if result == 0:
            latency = int((time.time() - start_time) * 1000)  # Convert to ms
            return {'online': True, 'latency': latency}
        else:
            return {'online': False, 'latency': None}
    except Exception:
        return {'online': False, 'latency': None}


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
    :root { --bg:#0f172a; --panel:#111827; --text:#e5e7eb; --muted:#9ca3af; --primary:#22c55e; --danger:#ef4444; --border:#1f2937; --accent:#3b82f6; --online:#22c55e; --offline:#6b7280; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif; background: var(--bg); color: var(--text); }
    header { padding: 24px; border-bottom: 1px solid var(--border); background: linear-gradient(180deg, rgba(59,130,246,0.25), rgba(34,197,94,0.2)); }
    header h1 { margin:0; font-size: 20px; }
    .container { max-width: 1200px; margin: 24px auto; padding: 0 16px; }
    .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
    .row { display:flex; gap:12px; flex-wrap:wrap; align-items:center; }
    input, button, select { height: 36px; border-radius: 8px; border: 1px solid var(--border); background:#0b1220; color: var(--text); padding: 0 12px; }
    input::placeholder { color: var(--muted); }
    button { cursor:pointer; border: none; }
    button.primary { background: var(--primary); color: #041d12; font-weight: 600; }
    button.secondary { background: var(--accent); color: #05142e; font-weight: 600; }
    button.danger { background: var(--danger); color: #330b0b; font-weight: 600; }
    button.success { background: #10b981; color: #042f1e; font-weight: 600; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border-bottom: 1px solid var(--border); padding: 10px; text-align: left; }
    th { color: var(--muted); font-weight: 500; }
    .actions { display:flex; gap:8px; }
    .badge { display:inline-block; padding:2px 8px; border-radius:999px; border:1px solid var(--border); color: var(--muted); font-size:12px; }
    .footer { color: var(--muted); font-size: 12px; text-align:center; margin-top: 12px; }
    .checkbox { width: 18px; height: 18px; }
    .status-indicator { display:inline-flex; align-items:center; gap:6px; }
    .status-dot { width:10px; height:10px; border-radius:50%; }
    .status-dot.online { background: var(--online); box-shadow: 0 0 8px var(--online); animation: pulse 2s infinite; }
    .status-dot.offline { background: var(--offline); }
    .latency { font-size:12px; color: var(--muted); margin-left:4px; }
    .latency.good { color: var(--online); }
    .latency.medium { color: #f59e0b; }
    .latency.bad { color: var(--danger); }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
    .monitor-controls { display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
    .monitor-controls label { color: var(--text); display:flex; align-items:center; gap:8px; }
    .switch { position:relative; display:inline-block; width:48px; height:24px; }
    .switch input { opacity:0; width:0; height:0; }
    .slider { position:absolute; cursor:pointer; top:0; left:0; right:0; bottom:0; background:#374151; border-radius:24px; transition:0.3s; }
    .slider:before { position:absolute; content:""; height:18px; width:18px; left:3px; bottom:3px; background:white; border-radius:50%; transition:0.3s; }
    input:checked + .slider { background: var(--primary); }
    input:checked + .slider:before { transform: translateX(24px); }
    .sortable { cursor: pointer; user-select: none; position: relative; }
    .sortable:hover { color: var(--primary); }
    .sortable::after { content: '⇅'; margin-left: 6px; opacity: 0.3; font-size: 14px; }
    .sortable.asc::after { content: '↑'; opacity: 1; color: var(--primary); }
    .sortable.desc::after { content: '↓'; opacity: 1; color: var(--primary); }
  </style>
</head>
<body>
  <header>
    <h1>WOL 唤醒工具</h1>
    <div class="badge">管理多台设备 · 支持搜索与批量唤醒</div>
  </header>
  <div class="container">
    <div class="panel">
      <div class="monitor-controls">
        <label>
          <span>实时监控</span>
          <label class="switch">
            <input type="checkbox" id="monitorToggle" />
            <span class="slider"></span>
          </label>
        </label>
        <label>
          <span>检测间隔</span>
          <select id="monitorInterval">
            <option value="5">5秒</option>
            <option value="10" selected>10秒</option>
            <option value="30">30秒</option>
            <option value="60">60秒</option>
          </select>
        </label>
        <button id="checkNow" class="secondary">立即检测</button>
        <label id="autostartLabel" style="display:none;">
          <span>开机自启</span>
          <label class="switch">
            <input type="checkbox" id="autostartToggle" />
            <span class="slider"></span>
          </label>
        </label>
        <button id="viewLogs" class="secondary" style="display:none;">查看日志</button>
        <div style="flex:1"></div>
        <span id="monitorStatus" style="color:var(--muted); font-size:12px;"></span>
      </div>
    </div>

    <div class="panel">
      <div class="row">
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
            <th style="width:120px" class="sortable" id="sortStatus">状态</th>
            <th>备注</th>
            <th>MAC 地址</th>
            <th>用户 IP</th>
            <th>广播 IP</th>
            <th style="width:340px">操作</th>
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
  checkAll: () => fetch('/api/check_all').then(r=>r.json()),
  checkOne: (ip) => fetch('/api/check', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ip})}).then(r=>r.json()),
  rdp: (ip) => fetch('/api/rdp', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ip})}).then(r=>r.json()),
  getAutostart: () => fetch('/api/autostart').then(r=>r.json()),
  setAutostart: (enable) => fetch('/api/autostart', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({enable})}).then(r=>r.json()),
  getLogs: (lines) => fetch('/api/logs?lines=' + (lines || 100)).then(r=>r.json()),
};

let devices = [];
let filtered = [];
let deviceStatus = {};
let monitorInterval = null;
let isMonitoring = false;
let sortOrder = null; // null, 'asc', 'desc'

function render(list){
  const tbody = document.getElementById('tbody');
  tbody.innerHTML = '';
  list.forEach(d => {
    const status = deviceStatus[d.mac] || {online: false, latency: null};
    const statusHtml = d.ip ? renderStatus(status) : '<span style="color:var(--muted); font-size:12px;">无IP</span>';
    const checkBtn = d.ip ? `<button class=\"secondary\" data-action=\"check\" data-mac=\"${d.mac}\" data-ip=\"${d.ip}\">检测</button>` : '';
    const rdpBtn = d.ip ? `<button class=\"success\" data-action=\"rdp\" data-ip=\"${d.ip}\">远程</button>` : '';
    
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input class=\"checkbox\" type=\"checkbox\" data-mac=\"${d.mac}\" /></td>
      <td>${statusHtml}</td>
      <td>${escapeHtml(d.remark || '')}</td>
      <td>${escapeHtml(d.mac)}</td>
      <td>${escapeHtml(d.ip || '')}</td>
      <td>${escapeHtml(d.broadcast_ip || '')}</td>
      <td class=\"actions\">
        ${checkBtn}
        ${rdpBtn}
        <button class=\"secondary\" data-action=\"wake\" data-mac=\"${d.mac}\">唤醒</button>
        <button class=\"danger\" data-action=\"del\" data-mac=\"${d.mac}\">删除</button>
      </td>`;
    tbody.appendChild(tr);
  });
}

function renderStatus(status){
  if(!status.online){
    return '<div class="status-indicator"><span class="status-dot offline"></span><span>离线</span></div>';
  }
  const latencyClass = status.latency < 50 ? 'good' : status.latency < 150 ? 'medium' : 'bad';
  return `<div class="status-indicator"><span class="status-dot online"></span><span>在线</span><span class="latency ${latencyClass}">${status.latency}ms</span></div>`;
}

function escapeHtml(str){
  return String(str).replace(/[&<>\"]/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[s]));
}

async function refresh(){
  devices = await api.list();
  const q = document.getElementById('search').value.trim();
  if(q){ filtered = await api.search(q); } else { filtered = devices; }
  applySortAndRender();
}

function applySortAndRender(){
  let toRender = [...filtered];
  
  if(sortOrder === 'asc'){
    // 在线的在上面
    toRender.sort((a, b) => {
      const statusA = deviceStatus[a.mac] || {online: false};
      const statusB = deviceStatus[b.mac] || {online: false};
      if(statusA.online && !statusB.online) return -1;
      if(!statusA.online && statusB.online) return 1;
      return 0;
    });
  } else if(sortOrder === 'desc'){
    // 离线的在上面
    toRender.sort((a, b) => {
      const statusA = deviceStatus[a.mac] || {online: false};
      const statusB = deviceStatus[b.mac] || {online: false};
      if(!statusA.online && statusB.online) return -1;
      if(statusA.online && !statusB.online) return 1;
      return 0;
    });
  }
  
  render(toRender);
  updateSortIndicator();
}

function updateSortIndicator(){
  const sortBtn = document.getElementById('sortStatus');
  sortBtn.classList.remove('asc', 'desc');
  if(sortOrder === 'asc'){
    sortBtn.classList.add('asc');
  } else if(sortOrder === 'desc'){
    sortBtn.classList.add('desc');
  }
}

async function checkAllDevices(){
  try {
    const results = await api.checkAll();
    results.forEach(r => {
      deviceStatus[r.mac] = {online: r.online, latency: r.latency};
    });
    applySortAndRender();
    updateMonitorStatus('最后检测: ' + new Date().toLocaleTimeString());
  } catch(e) {
    console.error('检测失败:', e);
  }
}

async function checkSingleDevice(mac, ip){
  try {
    const result = await api.checkOne(ip);
    deviceStatus[mac] = {online: result.online, latency: result.latency};
    applySortAndRender();
  } catch(e) {
    console.error('检测失败:', e);
  }
}

async function openRDP(ip){
  try {
    const res = await api.rdp(ip);
    if(res.error){
      alert('打开远程桌面失败: ' + res.error);
    }
  } catch(e) {
    alert('打开远程桌面失败: ' + e.message);
  }
}

function startMonitoring(){
  if(monitorInterval) return;
  const interval = parseInt(document.getElementById('monitorInterval').value) * 1000;
  isMonitoring = true;
  saveMonitorSettings();
  checkAllDevices();
  monitorInterval = setInterval(checkAllDevices, interval);
  updateMonitorStatus('监控中...');
}

function stopMonitoring(){
  if(monitorInterval){
    clearInterval(monitorInterval);
    monitorInterval = null;
  }
  isMonitoring = false;
  saveMonitorSettings();
  updateMonitorStatus('已停止');
}

function updateMonitorStatus(text){
  document.getElementById('monitorStatus').textContent = text;
}

function saveMonitorSettings(){
  const settings = {
    enabled: isMonitoring,
    interval: document.getElementById('monitorInterval').value
  };
  localStorage.setItem('monitorSettings', JSON.stringify(settings));
}

function loadMonitorSettings(){
  try {
    const saved = localStorage.getItem('monitorSettings');
    if(saved){
      const settings = JSON.parse(saved);
      document.getElementById('monitorInterval').value = settings.interval || '10';
      if(settings.enabled){
        document.getElementById('monitorToggle').checked = true;
        startMonitoring();
      }
    }
  } catch(e) {
    console.error('加载设置失败:', e);
  }
}

async function loadAutostartStatus(){
  try {
    const res = await api.getAutostart();
    if(res.enabled !== undefined){
      // Show autostart controls (Windows only)
      document.getElementById('autostartLabel').style.display = 'flex';
      document.getElementById('autostartToggle').checked = res.enabled;
    }
  } catch(e) {
    // Not on Windows or API not available
    console.log('开机自启功能不可用');
  }
}

async function checkLogsAvailable(){
  try {
    const res = await api.getLogs(1);
    if(res.logs || res.error){
      document.getElementById('viewLogs').style.display = 'block';
    }
  } catch(e) {
    console.log('日志功能不可用');
  }
}

function showLogsModal(){
  const modal = document.createElement('div');
  modal.style.cssText = 'position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.8); display:flex; align-items:center; justify-content:center; z-index:9999;';
  
  const content = document.createElement('div');
  content.style.cssText = 'background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:24px; max-width:800px; width:90%; max-height:80vh; display:flex; flex-direction:column;';
  
  const title = document.createElement('h3');
  title.textContent = '系统日志';
  title.style.cssText = 'margin:0 0 16px 0; color:var(--text);';
  
  const logArea = document.createElement('pre');
  logArea.style.cssText = 'flex:1; overflow:auto; background:#0b1220; border:1px solid var(--border); border-radius:8px; padding:12px; color:var(--text); font-size:12px; line-height:1.5; margin:0;';
  logArea.textContent = '加载中...';
  
  const closeBtn = document.createElement('button');
  closeBtn.textContent = '关闭';
  closeBtn.className = 'secondary';
  closeBtn.style.cssText = 'margin-top:16px; align-self:flex-end;';
  closeBtn.onclick = () => document.body.removeChild(modal);
  
  content.appendChild(title);
  content.appendChild(logArea);
  content.appendChild(closeBtn);
  modal.appendChild(content);
  document.body.appendChild(modal);
  
  // Load logs
  api.getLogs(200).then(res => {
    if(res.logs){
      logArea.textContent = res.logs;
      logArea.scrollTop = logArea.scrollHeight;
    } else if(res.error){
      logArea.textContent = '加载日志失败: ' + res.error;
    }
  });
  
  modal.onclick = (e) => {
    if(e.target === modal) document.body.removeChild(modal);
  };
}

function bindEvents(){
  document.getElementById('refresh').addEventListener('click', refresh);
  
  document.getElementById('sortStatus').addEventListener('click', () => {
    if(sortOrder === null){
      sortOrder = 'asc'; // 第一次点击：在线在上
    } else if(sortOrder === 'asc'){
      sortOrder = 'desc'; // 第二次点击：离线在上
    } else {
      sortOrder = null; // 第三次点击：取消排序
    }
    applySortAndRender();
  });
  
  document.getElementById('monitorToggle').addEventListener('change', (e) => {
    if(e.target.checked){
      startMonitoring();
    } else {
      stopMonitoring();
    }
  });
  
  document.getElementById('monitorInterval').addEventListener('change', () => {
    saveMonitorSettings();
    if(isMonitoring){
      stopMonitoring();
      startMonitoring();
    }
  });
  
  document.getElementById('checkNow').addEventListener('click', checkAllDevices);
  
  document.getElementById('autostartToggle').addEventListener('change', async (e) => {
    const res = await api.setAutostart(e.target.checked);
    if(res.ok){
      console.log('开机自启已' + (res.enabled ? '启用' : '禁用'));
    }
  });
  
  document.getElementById('viewLogs').addEventListener('click', showLogsModal);
  
  document.getElementById('add').addEventListener('click', async () => {
    const mac = document.getElementById('mac').value.trim();
    const ip = document.getElementById('ip').value.trim();
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
    if(action === 'rdp'){
      const ip = btn.getAttribute('data-ip');
      openRDP(ip);
    } else if(action === 'check'){
      const ip = btn.getAttribute('data-ip');
      btn.disabled = true;
      btn.textContent = '检测中...';
      await checkSingleDevice(mac, ip);
      btn.disabled = false;
      btn.textContent = '检测';
    } else if(action === 'wake'){
      btn.disabled = true;
      const originalText = btn.textContent;
      btn.textContent = '发送中...';
      try {
        const res = await api.wake(mac);
        if(res.error){ 
          alert(res.error); 
        } else { 
          btn.textContent = '已发送';
          setTimeout(() => { btn.textContent = originalText; btn.disabled = false; }, 1500);
        }
      } catch(e) {
        alert('唤醒失败: ' + e.message);
        btn.textContent = originalText;
        btn.disabled = false;
      }
      if(btn.textContent === '发送中...') {
        btn.textContent = originalText;
        btn.disabled = false;
      }
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
    
    const btn = document.getElementById('wakeSelected');
    btn.disabled = true;
    btn.textContent = '发送中...';
    
    let successCount = 0;
    let failCount = 0;
    const errors = [];
    
    for(const c of chks){
      const mac = c.getAttribute('data-mac');
      try {
        const res = await api.wake(mac);
        if(res.error){ 
          failCount++;
          errors.push(`${mac}: ${res.error}`);
        } else {
          successCount++;
        }
      } catch(e) {
        failCount++;
        errors.push(`${mac}: ${e.message}`);
      }
    }
    
    btn.disabled = false;
    btn.textContent = '唤醒选中';
    
    if(failCount > 0){
      alert(`批量唤醒完成\n成功: ${successCount}台\n失败: ${failCount}台\n\n错误详情:\n${errors.join('\n')}`);
    } else {
      alert(`已成功发送 ${successCount} 台设备的唤醒数据包`);
    }
  });
}

function debounce(fn, delay){
  let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn.apply(null, args), delay); };
}

(async function init(){ 
  bindEvents(); 
  await refresh(); 
  loadMonitorSettings();
  loadAutostartStatus();
  checkLogsAvailable();
})();
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


@app.route('/api/check', methods=['POST'])
def check_device():
    """Check if a device is online by testing port 3389."""
    data = request.get_json(force=True) or {}
    ip = data.get('ip', '')
    port = int(data.get('port') or 3389)
    timeout = float(data.get('timeout') or 1.0)
    
    if not ip:
        return jsonify({'error': 'IP 地址不能为空'}), 400
    
    result = check_port(ip, port, timeout)
    return jsonify(result)


def check_device_worker(device):
    """Worker function to check a single device."""
    ip = device.get('ip')
    mac = device.get('mac')
    
    if ip:
        status = check_port(ip, 3389, 1.0)
        return {
            'mac': mac,
            'online': status['online'],
            'latency': status['latency']
        }
    else:
        return {
            'mac': mac,
            'online': False,
            'latency': None
        }


@app.route('/api/check_all', methods=['GET'])
def check_all_devices():
    """Check online status for all devices using thread pool."""
    devices = load_devices()
    results = []
    
    # Use ThreadPoolExecutor for concurrent checking
    with ThreadPoolExecutor(max_workers=20) as executor:
        # Submit all tasks
        future_to_device = {executor.submit(check_device_worker, device): device for device in devices}
        
        # Collect results as they complete
        for future in as_completed(future_to_device):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                device = future_to_device[future]
                results.append({
                    'mac': device.get('mac'),
                    'online': False,
                    'latency': None
                })
    
    return jsonify(results)


@app.route('/api/rdp', methods=['POST'])
def open_rdp():
    """Open Remote Desktop Connection to specified IP."""
    data = request.get_json(force=True) or {}
    ip = data.get('ip', '')
    
    if not ip:
        return jsonify({'error': 'IP 地址不能为空'}), 400
    
    try:
        import subprocess
        import platform
        
        system = platform.system()
        
        if system == 'Windows':
            # Windows: 使用 mstsc 命令
            subprocess.Popen(['mstsc', f'/v:{ip}:3389'])
        elif system == 'Darwin':
            # macOS: 使用 open 命令打开 rdp:// 协议
            subprocess.Popen(['open', f'rdp://full%20address=s:{ip}:3389'])
        else:
            # Linux: 尝试使用 xfreerdp 或 rdesktop
            try:
                subprocess.Popen(['xfreerdp', f'/v:{ip}:3389'])
            except FileNotFoundError:
                try:
                    subprocess.Popen(['rdesktop', f'{ip}:3389'])
                except FileNotFoundError:
                    return jsonify({'error': '未找到远程桌面客户端'}), 500
        
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# -------------------- Windows Autostart --------------------

def is_windows():
    """Check if running on Windows."""
    return sys.platform == 'win32'


def get_autostart_status():
    """Check if autostart is enabled."""
    if not is_windows():
        return False
    
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                            r'Software\Microsoft\Windows\CurrentVersion\Run',
                            0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, 'WOL_Tool')
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            winreg.CloseKey(key)
            return False
    except Exception as e:
        logger.error(f'检查开机自启状态失败: {e}')
        return False


def set_autostart(enable=True):
    """Enable or disable autostart."""
    if not is_windows():
        return False
    
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Run',
                            0, winreg.KEY_SET_VALUE)
        
        if enable:
            exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
            winreg.SetValueEx(key, 'WOL_Tool', 0, winreg.REG_SZ, f'"{exe_path}"')
            logger.info('已启用开机自启')
        else:
            try:
                winreg.DeleteValue(key, 'WOL_Tool')
                logger.info('已禁用开机自启')
            except FileNotFoundError:
                pass
        
        winreg.CloseKey(key)
        return True
    except Exception as e:
        logger.error(f'设置开机自启失败: {e}')
        return False


@app.route('/api/autostart', methods=['GET'])
def get_autostart():
    """Get autostart status."""
    return jsonify({'enabled': get_autostart_status()})


@app.route('/api/autostart', methods=['POST'])
def toggle_autostart():
    """Toggle autostart."""
    data = request.get_json(force=True) or {}
    enable = data.get('enable', True)
    success = set_autostart(enable)
    return jsonify({'ok': success, 'enabled': get_autostart_status()})


@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Get log file content."""
    try:
        lines = int(request.args.get('lines', 100))
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                content = f.readlines()
                return jsonify({'logs': ''.join(content[-lines:])})
        return jsonify({'logs': '日志文件不存在'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# -------------------- System Tray --------------------

class TrayApp:
    def __init__(self, port=5050):
        self.port = port
        self.icon = None
        self.flask_thread = None
        
    def create_icon(self):
        """Create system tray icon."""
        try:
            from PIL import Image, ImageDraw
            import pystray
            
            # Create a simple icon
            width = 64
            height = 64
            image = Image.new('RGB', (width, height), color='#22c55e')
            dc = ImageDraw.Draw(image)
            dc.rectangle([16, 16, 48, 48], fill='#0f172a', outline='#22c55e', width=2)
            
            menu = pystray.Menu(
                pystray.MenuItem('打开界面', self.open_browser),
                pystray.MenuItem('切换开机自启', self.toggle_autostart),
                pystray.MenuItem('查看日志', self.open_log),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem('退出', self.quit_app)
            )
            
            self.icon = pystray.Icon('WOL_Tool', image, 'WOL 唤醒工具', menu)
            return self.icon
        except ImportError:
            logger.warning('pystray 未安装，系统托盘功能不可用')
            return None
    
    def open_browser(self, icon=None, item=None):
        """Open web interface in browser."""
        webbrowser.open(f'http://localhost:{self.port}')
        logger.info('打开Web界面')
    
    def toggle_autostart(self, icon=None, item=None):
        """Toggle autostart setting."""
        current = get_autostart_status()
        if set_autostart(not current):
            status = '已启用' if not current else '已禁用'
            logger.info(f'开机自启{status}')
    
    def open_log(self, icon=None, item=None):
        """Open log file."""
        if os.path.exists(LOG_FILE):
            if is_windows():
                os.startfile(LOG_FILE)
            else:
                webbrowser.open(f'file://{LOG_FILE}')
            logger.info('打开日志文件')
    
    def quit_app(self, icon=None, item=None):
        """Quit application."""
        logger.info('退出应用')
        if self.icon:
            self.icon.stop()
        os._exit(0)
    
    def run_flask(self):
        """Run Flask in a separate thread."""
        debug = not getattr(sys, 'frozen', False)
        app.run(host='0.0.0.0', port=self.port, debug=False, use_reloader=False)
    
    def start(self):
        """Start the application."""
        # Start Flask in background thread
        self.flask_thread = threading.Thread(target=self.run_flask, daemon=True)
        self.flask_thread.start()
        logger.info(f'Flask服务已启动: http://localhost:{self.port}')
        
        # Create and run system tray
        icon = self.create_icon()
        if icon:
            logger.info('系统托盘已启动')
            # Auto open browser on first start
            threading.Timer(1.5, self.open_browser).start()
            icon.run()
        else:
            # Fallback: run Flask in main thread
            logger.info('以无托盘模式运行')
            self.open_browser()
            self.run_flask()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '5050'))
    logger.info('=== WOL 唤醒工具启动 ===')
    
    # Check if running with system tray support
    if is_windows() and getattr(sys, 'frozen', False):
        # Running as packaged exe on Windows - use tray
        tray_app = TrayApp(port)
        tray_app.start()
    else:
        # Running in development mode or non-Windows
        debug = not getattr(sys, 'frozen', False)
        logger.info(f'开发模式启动: http://localhost:{port}')
        app.run(host='0.0.0.0', port=port, debug=debug)