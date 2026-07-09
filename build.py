#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lee el CSV de remisiones, limpia los datos y genera dashboard.html (cifrado)"""
import csv, re, json, os, base64
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "registro_manual_remisiones_2026.csv")
OUT = os.path.join(HERE, "dashboard.html")

PASSWORD = os.environ.get("DASH_PWD")  # clave via variable de entorno (no se guarda en el repo)
if not PASSWORD:
    raise SystemExit("Falta la clave: ejecuta con  DASH_PWD='tu_clave' python3 build.py")
PBKDF2_ITER = 250000


def encrypt_data(plaintext, password):
    salt = os.urandom(16)
    iv = os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITER)
    key = kdf.derive(password.encode("utf-8"))
    ct = AESGCM(key).encrypt(iv, plaintext.encode("utf-8"), None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return {"salt": b64(salt), "iv": b64(iv), "ct": b64(ct), "iter": PBKDF2_ITER}

BOTTLE_L = 0.330  # litros por botella

MONTHS = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio',
          'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

# (nombre, col botellas, col litros)  -> col None = ese estilo no tiene esa presentacion
STYLES = [
    ("Golden Ale", 5, 6),
    ("Irish Red Ale", 7, 8),
    ("APA", 9, 10),
    ("IPA", 11, 12),
    ("Stout", 13, 14),
    ("Hidromiel", 15, 16),
    ("Scottish", None, 17),
    ("German Pils", None, 18),
]
# temporada: (nombre_col, botellas_col, litros_col)
SEASONAL = [(19, 20, 21), (22, 23, 24)]


def clean_num(s):
    if s is None:
        return 0.0
    s = s.replace('\ufffc', '').replace('|', '').strip()
    if not s:
        return 0.0
    total, found = 0.0, False
    for p in re.split(r'\+', s):
        p = re.sub(r'[^0-9.,]', '', p.strip())
        if not p:
            continue
        if ',' in p and '.' in p:
            p = p.replace('.', '').replace(',', '.')
        elif ',' in p:
            p = p.replace(',', '.')
        try:
            total += float(p)
            found = True
        except ValueError:
            pass
    return total if found else 0.0


def parse_month(s):
    s = (s or '').strip()
    m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', s)
    if not m:
        return None
    mo, y = int(m.group(2)), int(m.group(3))
    if mo < 1 or mo > 12:
        return None
    if y < 2000:
        y = 2026
    return y, mo


def client_name(row):
    cli = (row[3] or '').strip()
    nue = (row[4] or '').strip()
    if cli.lower() in ('cliente nuevo', ''):
        return nue if nue else (cli if cli else '(Sin cliente)')
    return cli


def main():
    with open(CSV, newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    header = rows[0]
    records = []
    season_names = set()
    for row in rows[1:]:
        row = row + [''] * (30 - len(row))
        pm = parse_month(row[2])
        if pm is None:
            continue  # descarta fila de totales y filas vacias
        y, mo = pm
        styles = {}
        for name, cb, cl in STYLES:
            b = clean_num(row[cb]) if cb is not None else 0.0
            l = clean_num(row[cl]) if cl is not None else 0.0
            if b or l:
                styles[name] = [b, l]
        for cn, cb, cl in SEASONAL:
            b = clean_num(row[cb])
            l = clean_num(row[cl])
            if b or l:
                nm = (row[cn] or '').strip() or 'Temporada'
                nm = 'Temp: ' + nm
                season_names.add(nm)
                cur = styles.get(nm, [0.0, 0.0])
                styles[nm] = [cur[0] + b, cur[1] + l]
        if not styles:
            continue
        inv = (row[1] or '').strip()
        records.append({
            "cli": client_name(row),
            "mk": y * 100 + mo,
            "ml": f"{MONTHS[mo]} {y}",
            "inv": inv,
            "resp": (row[26] or '').strip(),
            "st": styles,
        })

    style_order = [s[0] for s in STYLES] + sorted(season_names)
    month_keys = sorted({r["mk"] for r in records})
    months = [{"k": k, "l": next(r["ml"] for r in records if r["mk"] == k)} for k in month_keys]

    # totales que trae la hoja (para validacion)
    sheet_totals = {
        "Golden Ale": [535, 37.1], "Irish Red Ale": [569, 229.85],
        "APA": [155, 35.55], "IPA": [299, 105], "Stout": [356, 95.65],
        "Hidromiel": [47, 97],
    }

    data = {"records": records, "styleOrder": style_order,
            "months": months, "sheetTotals": sheet_totals, "bottleL": BOTTLE_L}

    enc = encrypt_data(json.dumps(data, ensure_ascii=False), PASSWORD)
    html = TEMPLATE.replace("/*__ENC__*/", json.dumps(enc, ensure_ascii=False))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)

    # resumen consola
    tb = {s: 0.0 for s in style_order}
    tl = {s: 0.0 for s in style_order}
    for r in records:
        for s, (b, l) in r["st"].items():
            tb[s] += b
            tl[s] += l
    print(f"Registros validos: {len(records)}")
    print(f"Clientes unicos: {len({r['cli'] for r in records})}")
    print(f"Meses: {[m['l'] for m in months]}")
    print("Estilo               Botellas   Litros(barril)  TotalLiquido(L)")
    TB = TL = TT = 0.0
    for s in style_order:
        tot = tb[s] * BOTTLE_L + tl[s]
        TB += tb[s]; TL += tl[s]; TT += tot
        print(f"{s:20s} {tb[s]:8.0f} {tl[s]:14.2f} {tot:16.2f}")
    print(f"{'TOTAL':20s} {TB:8.0f} {TL:14.2f} {TT:16.2f}")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Registro Manual Remisiones 2026</title>
<style>
  :root{
    --bg:#0f1720; --panel:#16212e; --panel2:#1d2b3a; --line:#2b3d52;
    --txt:#e8eef5; --mut:#93a4b8; --acc:#f4a52b; --acc2:#3aa0ff;
    --g:#2ecc71; --warn:#ff6b6b;
  }
  *{box-sizing:border-box}
  body{margin:0;font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--txt);font-size:14px}
  header{background:linear-gradient(90deg,#1a2836,#0f1720);padding:18px 22px;border-bottom:2px solid var(--acc)}
  header h1{margin:0;font-size:20px;letter-spacing:.5px}
  header p{margin:4px 0 0;color:var(--mut);font-size:12px}
  .wrap{padding:18px 22px;max-width:1250px;margin:0 auto}
  .filters{display:flex;gap:14px;flex-wrap:wrap;align-items:end;margin-bottom:18px}
  .filters label{display:block;font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}
  select{background:var(--panel2);color:var(--txt);border:1px solid var(--line);border-radius:8px;padding:9px 12px;font-size:14px;min-width:230px}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-bottom:22px}
  .kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:15px 16px}
  .kpi .v{font-size:26px;font-weight:700}
  .kpi .l{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.5px;margin-top:3px}
  .kpi.acc .v{color:var(--acc)} .kpi.acc2 .v{color:var(--acc2)} .kpi.g .v{color:var(--g)}
  .kpi.warn{border-color:var(--warn)} .kpi.warn .v{color:var(--warn)}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:22px}
  .card h2{margin:0 0 14px;font-size:15px;color:var(--acc)}
  table{border-collapse:collapse;width:100%;font-size:13px}
  th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
  th:first-child,td:first-child{text-align:left}
  thead th{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.4px;position:sticky;top:0;background:var(--panel)}
  tbody tr:hover{background:var(--panel2)}
  tfoot td{font-weight:700;border-top:2px solid var(--acc);color:var(--acc)}
  td.bad{color:var(--warn);font-weight:700}
  tr.badrow td:first-child{border-left:3px solid var(--warn)}
  .scroll{overflow:auto;max-height:460px;border-radius:8px}
  .bar{height:10px;background:var(--acc);border-radius:5px;display:inline-block;vertical-align:middle}
  .barwrap{display:flex;align-items:center;gap:8px;justify-content:flex-end}
  .muted{color:var(--mut);font-size:12px}
  .pill{background:var(--panel2);border:1px solid var(--line);border-radius:20px;padding:2px 10px;font-size:11px;color:var(--mut)}
  .note{font-size:11px;color:var(--mut);margin-top:8px}
  body.locked header,body.locked .wrap{display:none}
  #gate{position:fixed;inset:0;background:radial-gradient(circle at 50% 30%,#16212e,#0b1119);
    display:flex;align-items:center;justify-content:center;z-index:1000}
  #gate.hide{display:none}
  .gatebox{background:var(--panel);border:1px solid var(--line);border-radius:16px;
    padding:32px 30px;width:320px;text-align:center;box-shadow:0 10px 40px rgba(0,0,0,.5)}
  .gatebox h1{font-size:18px;margin:0 0 4px} .gatebox p{color:var(--mut);font-size:12px;margin:0 0 20px}
  .gatebox input{width:100%;background:var(--panel2);border:1px solid var(--line);border-radius:10px;
    padding:12px 14px;color:var(--txt);font-size:15px;letter-spacing:2px;margin-bottom:12px}
  .gatebox input:focus{outline:none;border-color:var(--acc)}
  .gatebox button{width:100%;background:var(--acc);color:#1a1200;border:0;border-radius:10px;
    padding:12px;font-size:15px;font-weight:700;cursor:pointer}
  .gatebox button:hover{filter:brightness(1.08)}
  .gateerr{color:var(--warn);font-size:12px;height:16px;margin-top:10px}
</style>
</head>
<body class="locked">
<div id="gate">
  <div class="gatebox">
    <h1>&#128274; Dashboard Maestro</h1>
    <p>Registro Manual Remisiones 2026</p>
    <form id="gateForm" autocomplete="off">
      <input type="password" id="gatePwd" placeholder="Clave de ingreso" autocomplete="current-password">
      <button type="submit" id="gateBtn">Ingresar</button>
    </form>
    <div class="gateerr" id="gateErr"></div>
  </div>
</div>
<header>
  <h1>&#127866; Registro Manual Remisiones 2026</h1>
  <p>Dashboard de remisiones &middot; botellas 0.330 L &middot; litros de barril &middot; total de l&iacute;quido por estilo</p>
</header>
<div class="wrap">
  <div class="filters">
    <div><label>Cliente</label><select id="fCli"></select></div>
    <div><label>Mes</label><select id="fMes"></select></div>
    <div><span class="pill" id="cntRec"></span></div>
  </div>

  <div class="kpis" id="kpis"></div>

  <div class="card">
    <h2>Por estilo &mdash; botellas, litros y total de l&iacute;quido</h2>
    <table id="tStyle"></table>
    <div class="note">Total l&iacute;quido = (botellas &times; 0.330 L) + litros de barril. La barra representa el total de l&iacute;quido del estilo.</div>
  </div>

  <div class="card">
    <h2>&#129534; Facturado / Remisionado por mes (Facturas Fe vs Recibos RC)</h2>
    <table id="tEmpty"></table>
    <div class="note">Separaci&oacute;n de la columna <b>Facturaci&oacute;n/Recibo de Caja</b>: <b>Fe</b>=Factura, <b>RC</b>=Recibo de Caja, <b>Incompleta</b>=documento sin n&uacute;mero, <b>Vac&iacute;a</b>=en blanco o nota (Muestras, Cancelado, no facturar, impulso, Donaci&oacute;n, capacitaci&oacute;n, activaci&oacute;n, no enviado, no contestan). Pendientes = incompletas + vac&iacute;as.</div>
  </div>

  <div class="card">
    <h2>&#128203; Detalle de remisiones pendientes (vac&iacute;as e incompletas)</h2>
    <div class="scroll"><table id="tEmptyDet"></table></div>
    <div class="note">Lista para gestionar: cada fila afecta el inventario y falta emitir documento o justificar. Respeta los filtros de arriba.</div>
  </div>

  <div class="card">
    <h2>Facturas / remisiones por cliente y mes</h2>
    <div class="scroll"><table id="tPivot"></table></div>
    <div class="note">Cada celda = n&uacute;mero de remisiones del cliente en ese mes. Usa el filtro de cliente para enfocar uno solo.</div>
  </div>
</div>

<script>
const ENC = /*__ENC__*/;
let DATA = null, BL = 0.330;
const fmt = (n,d=0)=> n.toLocaleString('es-CO',{minimumFractionDigits:d,maximumFractionDigits:d});

// ---- acceso con clave (descifrado AES-256-GCM en el navegador) ----
const b64d = s => Uint8Array.from(atob(s), c=>c.charCodeAt(0));
async function unlock(pwd){
  const enc = new TextEncoder();
  const km = await crypto.subtle.importKey('raw', enc.encode(pwd), 'PBKDF2', false, ['deriveKey']);
  const key = await crypto.subtle.deriveKey(
    {name:'PBKDF2', salt:b64d(ENC.salt), iterations:ENC.iter, hash:'SHA-256'},
    km, {name:'AES-GCM', length:256}, false, ['decrypt']);
  const pt = await crypto.subtle.decrypt({name:'AES-GCM', iv:b64d(ENC.iv)}, key, b64d(ENC.ct));
  DATA = JSON.parse(new TextDecoder().decode(pt));
  BL = DATA.bottleL;
}
window.addEventListener('DOMContentLoaded', ()=>{
  const form=document.getElementById('gateForm'), err=document.getElementById('gateErr'),
        pwd=document.getElementById('gatePwd'), btn=document.getElementById('gateBtn');
  pwd.focus();
  form.addEventListener('submit', async e=>{
    e.preventDefault(); err.textContent=''; btn.disabled=true; btn.textContent='Verificando...';
    try{
      await unlock(pwd.value);
      document.getElementById('gate').classList.add('hide');
      document.body.classList.remove('locked');
      init();
    }catch(ex){
      err.textContent='Clave incorrecta';
      btn.disabled=false; btn.textContent='Ingresar'; pwd.value=''; pwd.focus();
    }
  });
});

const selCli = document.getElementById('fCli');
const selMes = document.getElementById('fMes');

// clasifica la columna B: fe=Factura, rc=Recibo de Caja, incompleta, vacia (blanco o nota)
function classB(inv){
  const raw = (inv||'').trim();
  if(!raw) return 'vacia';
  const s = raw.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'');
  if(/(muestra|cancel|no facturar|impulso|donacion|capacitacion|activacion|enviado|contestan)/.test(s)) return 'vacia';
  if(/^rc\s*\d/.test(s)) return 'rc';
  if(/^fe\s*\d/.test(s)) return 'fe';
  return 'incompleta';
}
const CATLBL = {vacia:'Vac&iacute;a', incompleta:'Incompleta', fe:'Factura', rc:'Recibo'};
function labelB(inv){
  const c = classB(inv);
  if(c==='vacia') return (inv&&inv.trim())? inv : '(vac&iacute;a)';
  if(c==='incompleta') return inv + ' (incompleta)';
  return inv;
}

function init(){
  const clients = [...new Set(DATA.records.map(r=>r.cli))].sort((a,b)=>a.localeCompare(b,'es'));
  selCli.innerHTML = '<option value="">Todos los clientes ('+clients.length+')</option>' +
    clients.map(c=>`<option>${c}</option>`).join('');
  selMes.innerHTML = '<option value="">Todos los meses</option>' +
    DATA.months.map(m=>`<option value="${m.k}">${m.l}</option>`).join('');
  selCli.onchange = selMes.onchange = render;
  render();
}

function filtered(){
  const c = selCli.value, m = selMes.value;
  return DATA.records.filter(r=> (!c||r.cli===c) && (!m||String(r.mk)===m));
}

function render(){
  const recs = filtered();
  document.getElementById('cntRec').textContent = recs.length + ' remisiones';

  // ---- agregados por estilo ----
  const bs={}, ls={};
  DATA.styleOrder.forEach(s=>{bs[s]=0;ls[s]=0;});
  let totBot=0, totLit=0;
  recs.forEach(r=>{
    for(const s in r.st){ bs[s]+=r.st[s][0]; ls[s]+=r.st[s][1]; }
  });
  const styleRows = DATA.styleOrder.filter(s=>bs[s]||ls[s]).map(s=>{
    const liq = bs[s]*BL + ls[s];
    totBot+=bs[s]; totLit+=ls[s];
    return {s, b:bs[s], l:ls[s], liq};
  });
  const totLiq = totBot*BL + totLit;
  const maxLiq = Math.max(1,...styleRows.map(r=>r.liq));

  // ---- KPIs ----
  const cat = {fe:0, rc:0, incompleta:0, vacia:0};
  recs.forEach(r=>{ cat[classB(r.inv)]++; });
  const pendRecs = recs.filter(r=>{const c=classB(r.inv); return c==='vacia'||c==='incompleta';});
  document.getElementById('kpis').innerHTML = `
    <div class="kpi"><div class="v">${fmt(recs.length)}</div><div class="l">Remisiones</div></div>
    <div class="kpi acc2"><div class="v">${fmt(totBot)}</div><div class="l">Botellas 0.330 L</div></div>
    <div class="kpi"><div class="v">${fmt(totLit,1)}</div><div class="l">Litros de barril</div></div>
    <div class="kpi acc"><div class="v">${fmt(totLiq,1)}</div><div class="l">Total l&iacute;quido (L)</div></div>
    <div class="kpi g"><div class="v">${fmt(cat.fe)}</div><div class="l">Facturas (Fe)</div></div>
    <div class="kpi g"><div class="v">${fmt(cat.rc)}</div><div class="l">Recibos de Caja (RC)</div></div>
    <div class="kpi warn"><div class="v">${fmt(cat.incompleta)}</div><div class="l">Incompletas</div></div>
    <div class="kpi warn"><div class="v">${fmt(cat.vacia)}</div><div class="l">Vac&iacute;as</div></div>`;

  // ---- tabla estilos ----
  let h = `<thead><tr><th>Estilo</th><th>Botellas (0.330 L)</th><th>Litros en botella</th>
    <th>Litros de barril</th><th>Total l&iacute;quido (L)</th></tr></thead><tbody>`;
  styleRows.forEach(r=>{
    const w = Math.round(r.liq/maxLiq*120);
    h += `<tr><td>${r.s}</td><td>${fmt(r.b)}</td><td>${fmt(r.b*BL,1)}</td>
      <td>${fmt(r.l,1)}</td><td><div class="barwrap"><span>${fmt(r.liq,1)}</span>
      <span class="bar" style="width:${w}px"></span></div></td></tr>`;
  });
  h += `</tbody><tfoot><tr><td>TOTAL</td><td>${fmt(totBot)}</td><td>${fmt(totBot*BL,1)}</td>
    <td>${fmt(totLit,1)}</td><td>${fmt(totLiq,1)}</td></tr></tfoot>`;
  document.getElementById('tStyle').innerHTML = h;

  // ---- pivote cliente x mes ----
  const months = selMes.value ? DATA.months.filter(m=>String(m.k)===selMes.value) : DATA.months;
  const clis = [...new Set(recs.map(r=>r.cli))].sort((a,b)=>a.localeCompare(b,'es'));
  const cell = {}; const rowTot={}; const colTot={}; let grand=0;
  clis.forEach(c=>{cell[c]={};rowTot[c]=0;});
  months.forEach(m=>colTot[m.k]=0);
  recs.forEach(r=>{
    cell[r.cli][r.mk]=(cell[r.cli][r.mk]||0)+1;
    rowTot[r.cli]++; colTot[r.mk]=(colTot[r.mk]||0)+1; grand++;
  });
  clis.sort((a,b)=>rowTot[b]-rowTot[a]);
  let p = `<thead><tr><th>Cliente</th>` + months.map(m=>`<th>${m.l}</th>`).join('') +
    `<th>Total</th></tr></thead><tbody>`;
  clis.forEach(c=>{
    p += `<tr><td>${c}</td>` + months.map(m=>`<td>${cell[c][m.k]||''}</td>`).join('') +
      `<td>${fmt(rowTot[c])}</td></tr>`;
  });
  p += `</tbody><tfoot><tr><td>TOTAL</td>` +
    months.map(m=>`<td>${fmt(colTot[m.k]||0)}</td>`).join('') + `<td>${fmt(grand)}</td></tr></tfoot>`;
  document.getElementById('tPivot').innerHTML = p;

  // ---- Facturado/Remisionado por mes (Fe / RC / incompleta / vacia) ----
  const mList = selMes.value ? DATA.months.filter(m=>String(m.k)===selMes.value) : DATA.months;
  const byM={};
  mList.forEach(m=>{byM[m.k]={t:0,fe:0,rc:0,incompleta:0,vacia:0};});
  recs.forEach(r=>{ const c=classB(r.inv); if(!byM[r.mk]) return; byM[r.mk].t++; byM[r.mk][c]++; });
  let e = `<thead><tr><th>Mes</th><th>Remisiones</th><th>Facturas (Fe)</th><th>Recibos (RC)</th>
    <th>Incompletas</th><th>Vac&iacute;as</th><th>% pendientes</th></tr></thead><tbody>`;
  const T={t:0,fe:0,rc:0,incompleta:0,vacia:0};
  mList.forEach(m=>{
    const x=byM[m.k]; for(const k in T) T[k]+=x[k];
    const pend=x.incompleta+x.vacia; const pct=x.t? pend/x.t*100:0;
    e += `<tr><td>${m.l}</td><td>${fmt(x.t)}</td><td>${fmt(x.fe)}</td><td>${fmt(x.rc)}</td>
      <td class="${x.incompleta?'bad':''}">${fmt(x.incompleta)}</td>
      <td class="${x.vacia?'bad':''}">${fmt(x.vacia)}</td><td>${fmt(pct,1)}%</td></tr>`;
  });
  const Tpend=T.incompleta+T.vacia;
  e += `</tbody><tfoot><tr><td>TOTAL</td><td>${fmt(T.t)}</td><td>${fmt(T.fe)}</td><td>${fmt(T.rc)}</td>
    <td>${fmt(T.incompleta)}</td><td>${fmt(T.vacia)}</td><td>${fmt(T.t?Tpend/T.t*100:0,1)}%</td></tr></tfoot>`;
  document.getElementById('tEmpty').innerHTML = e;

  // ---- detalle de remisiones pendientes (vacias + incompletas) ----
  const det = pendRecs.slice().sort((a,b)=> a.mk-b.mk || a.cli.localeCompare(b.cli,'es'));
  let d = `<thead><tr><th>Mes</th><th>Cliente</th><th>Facturado/Remisionado</th><th>Responsable</th><th>Estilos (bot./L)</th></tr></thead><tbody>`;
  if(!det.length){
    d += `<tr><td colspan="5" class="muted">Sin remisiones pendientes para el filtro actual &#9989;</td></tr>`;
  } else {
    det.forEach(r=>{
      const items = Object.keys(r.st).map(s=>{
        const [b,l]=r.st[s]; const parts=[];
        if(b) parts.push(fmt(b)+' bot'); if(l) parts.push(fmt(l,1)+' L');
        return s+': '+parts.join(' + ');
      }).join(' &middot; ');
      d += `<tr class="badrow"><td>${r.ml}</td><td>${r.cli}</td><td class="bad">${labelB(r.inv)}</td><td>${r.resp||'&mdash;'}</td><td style="text-align:left">${items}</td></tr>`;
    });
  }
  d += `</tbody>`;
  document.getElementById('tEmptyDet').innerHTML = d;
}
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()
