#!/usr/bin/env python3
"""Local manager for arthaud-proust-archive GitHub repos."""

import json, subprocess, webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

ORG  = "arthaud-proust-archive"
PORT = 7463

def gh(*args, stdin=None):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, input=stdin)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout

def list_repos():
    data = json.loads(gh(
        "repo", "list", ORG,
        "--json", "name,nameWithOwner,isArchived,isPrivate,description,repositoryTopics",
        "--limit", "200",
    ))
    for r in data:
        r["topics"] = [t["name"] for t in (r.pop("repositoryTopics", None) or [])]
        r["description"] = r.get("description") or ""
    return sorted(data, key=lambda r: r["name"])

def apply_changes(repo, changes):
    errors = []

    if "isArchived" in changes:
        try:
            if changes["isArchived"]:
                gh("repo", "archive", repo, "--yes")
            else:
                gh("repo", "unarchive", repo, "--yes")
        except RuntimeError as e:
            errors.append(str(e))

    if "description" in changes:
        try:
            gh("repo", "edit", repo, "--description", changes["description"])
        except RuntimeError as e:
            errors.append(str(e))

    if "isPrivate" in changes:
        vis = "private" if changes["isPrivate"] else "public"
        try:
            gh("repo", "edit", repo, "--visibility", vis,
               "--accept-visibility-change-consequences")
        except RuntimeError as e:
            errors.append(str(e))

    if "topics" in changes:
        try:
            gh("api", "-X", "PUT", f"repos/{repo}/topics",
               "--input", "-", stdin=json.dumps({"names": changes["topics"]}))
        except RuntimeError as e:
            errors.append(str(e))

    return errors


HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>arthaud-proust-archive</title>
<script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-950 text-gray-100 text-sm font-mono min-h-screen">

<div class="max-w-screen-2xl mx-auto px-6 py-8">

  <!-- Header -->
  <div class="flex items-center justify-between mb-6">
    <h1 class="text-base font-semibold tracking-tight">
      arthaud-proust-archive
      <span id="repoCount" class="ml-3 text-gray-600 font-normal text-xs"></span>
    </h1>
    <button onclick="loadRepos()"
            class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 rounded text-gray-400 hover:text-gray-200 text-xs transition-colors">
      ↻ Rafraîchir
    </button>
  </div>

  <!-- Bulk toolbar -->
  <div id="toolbar" class="hidden mb-4 p-3 bg-gray-800/80 border border-gray-700 rounded-lg flex items-center gap-2 flex-wrap">
    <span id="selCount" class="text-gray-400 text-xs mr-1 shrink-0"></span>
    <div class="w-px h-4 bg-gray-600"></div>
    <button onclick="bulkAction('archive')"   class="tbtn hover:bg-yellow-900/60 hover:text-yellow-300">Archiver</button>
    <button onclick="bulkAction('unarchive')" class="tbtn hover:bg-emerald-900/60 hover:text-emerald-300">Désarchiver</button>
    <div class="w-px h-4 bg-gray-600"></div>
    <button onclick="bulkAction('private')" class="tbtn hover:bg-gray-600">→ Privé</button>
    <button onclick="bulkAction('public')"  class="tbtn hover:bg-blue-900/60 hover:text-blue-300">→ Public</button>
    <div class="w-px h-4 bg-gray-600"></div>
    <div class="flex items-center gap-1.5">
      <input id="bulkTag" type="text" placeholder="topic…"
             class="bg-gray-700 border border-gray-600 text-xs px-2 py-1 rounded w-32 outline-none focus:border-indigo-500 placeholder-gray-600"
             onkeydown="if(event.key==='Enter') bulkAddTag()">
      <button onclick="bulkAddTag()"    class="tbtn bg-emerald-900/40 hover:bg-emerald-800/60 text-emerald-400">+ Ajouter</button>
      <button onclick="bulkRemoveTag()" class="tbtn bg-red-900/30 hover:bg-red-800/60 text-red-400">− Retirer</button>
    </div>
  </div>

  <!-- Errors -->
  <div id="errBox" class="hidden mb-4 p-3 bg-red-900/30 border border-red-700 rounded text-red-300 text-xs"></div>

  <!-- Loading -->
  <div id="loading" class="text-gray-600 text-center py-24">Chargement…</div>

  <!-- Table -->
  <div id="tableWrap" class="hidden overflow-x-auto">
    <table class="w-full border-collapse">
      <thead>
        <tr class="text-gray-500 border-b border-gray-800 text-xs uppercase tracking-wider">
          <th class="pb-2 pr-3 w-6 text-left">
            <input type="checkbox" id="selectAll" class="cursor-pointer accent-indigo-500"
                   onchange="toggleSelectAll(this.checked)">
          </th>
          <th class="pb-2 pr-4 text-left">Repo</th>
          <th class="pb-2 pr-4 text-left w-24">Statut</th>
          <th class="pb-2 pr-4 text-left w-20">Accès</th>
          <th class="pb-2 pr-4 text-left w-72">Topics</th>
          <th class="pb-2 text-left">Description</th>
          <th class="pb-2 w-12"></th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
</div>

<!-- Toast -->
<div id="toast" class="hidden fixed bottom-5 right-5 px-4 py-2.5 rounded shadow-xl text-xs"></div>

<style>
  .tbtn { @apply px-2.5 py-1 bg-gray-700 rounded text-xs text-gray-300 cursor-pointer transition-colors; }
</style>

<script>
let repos = [];
let pending = {};

async function loadRepos() {
  show('loading'); hide('tableWrap'); hide('errBox'); hide('toolbar');
  try {
    const r = await fetch('/api/repos');
    if (!r.ok) throw new Error(await r.text());
    repos = await r.json();
    pending = {};
    render();
    document.getElementById('repoCount').textContent = repos.length + ' repos';
  } catch(e) {
    document.getElementById('errBox').textContent = e.message;
    show('errBox');
  } finally {
    hide('loading');
  }
}

function render() {
  const tbody = document.getElementById('tbody');
  tbody.innerHTML = '';
  repos.forEach(r => tbody.appendChild(makeRow(r)));
  show('tableWrap');
}

function makeRow(r) {
  const p = pending[r.nameWithOwner] || {};
  const archived  = p.isArchived  ?? r.isArchived;
  const priv      = p.isPrivate   ?? r.isPrivate;
  const topics    = p.topics      ?? [...r.topics];
  const desc      = p.description ?? r.description;
  const isDirty   = !!pending[r.nameWithOwner];
  const nwo       = esc(r.nameWithOwner);

  const tr = document.createElement('tr');
  tr.className = 'border-b border-gray-800/50 hover:bg-gray-900/30 group';
  tr.dataset.repo = r.nameWithOwner;

  tr.innerHTML = `
    <td class="py-2 pr-3">
      <input type="checkbox" class="row-cb cursor-pointer accent-indigo-500"
             data-repo="${nwo}" onchange="updateToolbar()">
    </td>
    <td class="py-2 pr-4">
      <a href="https://github.com/${nwo}" target="_blank"
         class="text-indigo-400 hover:text-indigo-200 hover:underline">${esc(r.name)}</a>
    </td>
    <td class="py-2 pr-4">
      <button onclick="toggleField('${nwo}','isArchived')"
              class="px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                archived
                  ? 'bg-yellow-900/50 text-yellow-400 hover:bg-emerald-900/50 hover:text-emerald-400'
                  : 'bg-gray-800 text-gray-400 hover:bg-yellow-900/50 hover:text-yellow-400'
              }">
        ${archived ? 'archivé' : 'actif'}
      </button>
    </td>
    <td class="py-2 pr-4">
      <button onclick="toggleField('${nwo}','isPrivate')"
              class="px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                priv
                  ? 'bg-gray-800 text-gray-500 hover:bg-blue-900/50 hover:text-blue-400'
                  : 'bg-blue-900/40 text-blue-400 hover:bg-gray-800 hover:text-gray-500'
              }">
        ${priv ? 'privé' : 'public'}
      </button>
    </td>
    <td class="py-2 pr-4">
      <div class="flex flex-wrap gap-1 items-center">
        ${topics.map(t => `
          <span class="inline-flex items-center gap-0.5 bg-indigo-900/40 text-indigo-300 px-1.5 py-0.5 rounded text-xs">
            ${esc(t)}
            <button onclick="removeTopic('${nwo}','${esc(t)}')"
                    class="text-indigo-600 hover:text-red-400 leading-none ml-0.5">×</button>
          </span>`).join('')}
        <input type="text" placeholder="＋"
               class="bg-transparent text-xs text-gray-500 w-5 outline-none placeholder-gray-700 focus:w-20 focus:text-gray-100 focus:placeholder-gray-500 transition-all cursor-text border-b border-transparent focus:border-indigo-500"
               onkeydown="if(event.key==='Enter'||event.key===','){event.preventDefault();addTopic('${nwo}',this)}"
               onblur="if(this.value.trim()) addTopic('${nwo}',this)">
      </div>
    </td>
    <td class="py-2">
      <input type="text" value="${esc(desc)}" placeholder="Aucune description"
             class="bg-transparent border-b border-transparent hover:border-gray-700 focus:border-indigo-500 text-gray-300 placeholder-gray-700 outline-none w-full transition-colors"
             oninput="markDirty('${nwo}','description',this.value)">
    </td>
    <td class="py-2 pl-2">
      <button onclick="saveRow('${nwo}')"
              class="save-btn text-xs px-2 py-1 rounded transition-colors ${isDirty ? 'bg-indigo-700 hover:bg-indigo-600 text-white' : 'invisible'}">
        ✓
      </button>
    </td>
  `;
  return tr;
}

function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function getRepo(nwo)  { return repos.find(r => r.nameWithOwner === nwo); }
function show(id)      { document.getElementById(id).classList.remove('hidden'); }
function hide(id)      { document.getElementById(id).classList.add('hidden'); }

function markDirty(nwo, field, value) {
  if (!pending[nwo]) pending[nwo] = {};
  pending[nwo][field] = value;
  const tr = document.querySelector(`tr[data-repo="${nwo}"]`);
  if (tr) tr.querySelector('.save-btn').classList.remove('invisible');
}

function refreshRow(nwo) {
  const old = document.querySelector(`tr[data-repo="${nwo}"]`);
  const r = getRepo(nwo);
  if (old && r) old.replaceWith(makeRow(r));
}

function toggleField(nwo, field) {
  const r = getRepo(nwo);
  const cur = (pending[nwo]?.[field]) ?? r[field];
  markDirty(nwo, field, !cur);
  refreshRow(nwo);
}

async function addTopic(nwo, input) {
  const val = input.value.trim().replace(/,$/, '').toLowerCase().replace(/\s+/g,'-');
  input.value = '';
  if (!val) return;
  const r = getRepo(nwo);
  const topics = [...(pending[nwo]?.topics ?? r.topics)];
  if (topics.includes(val)) return;
  topics.push(val);
  await saveTopics(nwo, topics);
}

async function removeTopic(nwo, topic) {
  const r = getRepo(nwo);
  const topics = [...(pending[nwo]?.topics ?? r.topics)].filter(t => t !== topic);
  await saveTopics(nwo, topics);
}

async function saveTopics(nwo, topics) {
  const [result] = await post('/api/update', { repo: nwo, changes: { topics } });
  if (result.ok) {
    getRepo(nwo).topics = topics;
    delete pending[nwo]?.topics;
    if (pending[nwo] && !Object.keys(pending[nwo]).length) delete pending[nwo];
    refreshRow(nwo);
  } else {
    toast('Erreur topics : ' + result.errors.join(' | '), 'err');
  }
}

async function saveRow(nwo) {
  const changes = pending[nwo];
  if (!changes) return;
  const btn = document.querySelector(`tr[data-repo="${nwo}"] .save-btn`);
  if (btn) { btn.textContent = '…'; btn.disabled = true; }
  const [result] = await post('/api/update', { repo: nwo, changes });
  if (result.ok) {
    Object.assign(getRepo(nwo), changes);
    delete pending[nwo];
    refreshRow(nwo);
    toast('Sauvegardé ✓', 'ok');
  } else {
    toast('Erreur : ' + result.errors.join(' | '), 'err');
    if (btn) { btn.textContent = '✓'; btn.disabled = false; }
  }
}

function getSelected() {
  return [...document.querySelectorAll('.row-cb:checked')].map(cb => cb.dataset.repo);
}

function toggleSelectAll(checked) {
  document.querySelectorAll('.row-cb').forEach(cb => cb.checked = checked);
  updateToolbar();
}

function updateToolbar() {
  const sel = getSelected();
  const tb = document.getElementById('toolbar');
  if (sel.length) {
    show('toolbar');
    document.getElementById('selCount').textContent = sel.length + ' sélectionné' + (sel.length > 1 ? 's' : '');
  } else {
    hide('toolbar');
  }
  document.getElementById('selectAll').indeterminate =
    sel.length > 0 && sel.length < repos.length;
}

async function bulkAction(action) {
  const sel = getSelected();
  if (!sel.length) return;
  const map = { archive: {isArchived:true}, unarchive: {isArchived:false},
                private: {isPrivate:true},  public:    {isPrivate:false} };
  await runBulk(sel, map[action]);
}

async function bulkAddTag() {
  const tag = normTag();
  if (!tag) return;
  const updates = getSelected().map(nwo => {
    const r = getRepo(nwo);
    const topics = [...(pending[nwo]?.topics ?? r.topics)];
    if (!topics.includes(tag)) topics.push(tag);
    return { nwo, changes: { topics } };
  });
  await runBulkCustom(updates);
  document.getElementById('bulkTag').value = '';
}

async function bulkRemoveTag() {
  const tag = normTag();
  if (!tag) return;
  const updates = getSelected().map(nwo => {
    const r = getRepo(nwo);
    const topics = [...(pending[nwo]?.topics ?? r.topics)].filter(t => t !== tag);
    return { nwo, changes: { topics } };
  });
  await runBulkCustom(updates);
  document.getElementById('bulkTag').value = '';
}

function normTag() {
  return document.getElementById('bulkTag').value.trim().toLowerCase().replace(/\s+/g,'-');
}

async function runBulk(repos, changes) {
  await runBulkCustom(repos.map(nwo => ({ nwo, changes })));
}

async function runBulkCustom(updates) {
  let ok = 0, fail = 0;
  for (const { nwo, changes } of updates) {
    const [r] = await post('/api/update', { repo: nwo, changes });
    if (r.ok) {
      Object.assign(getRepo(nwo), changes);
      delete pending[nwo];
      refreshRow(nwo);
      ok++;
    } else {
      fail++;
    }
  }
  toast(`${ok} mis à jour${fail ? ` — ${fail} erreur(s)` : ''}`, fail ? 'warn' : 'ok');
}

async function post(url, body) {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return r.json();
}

function toast(msg, type='ok') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `fixed bottom-5 right-5 px-4 py-2.5 rounded shadow-xl text-xs ${
    type === 'ok'   ? 'bg-emerald-900 text-emerald-200' :
    type === 'err'  ? 'bg-red-900 text-red-200' :
                      'bg-yellow-900 text-yellow-200'
  }`;
  show('toast');
  clearTimeout(el._t);
  el._t = setTimeout(() => hide('toast'), 3500);
}

loadRepos();
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def send_json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(b))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", ""):
            b = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html;charset=utf-8")
            self.send_header("Content-Length", len(b))
            self.end_headers()
            self.wfile.write(b)
        elif path == "/api/repos":
            try:
                self.send_json(list_repos())
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if urlparse(self.path).path != "/api/update":
            self.send_response(404); self.end_headers(); return
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        repo_list = body.get("repos") or ([body["repo"]] if body.get("repo") else [])
        changes = body.get("changes", {})
        self.send_json([
            {"repo": r, "ok": not (errs := apply_changes(r, changes)), "errors": errs}
            for r in repo_list
        ])


if __name__ == "__main__":
    srv = HTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"▸ {url}  (Ctrl-C pour quitter)")
    webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêté.")
