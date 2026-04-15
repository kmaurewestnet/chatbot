/* =============================================================
   Telecom Agent — Dev UI — Alpine.js component
   ============================================================= */

const BASE = window.location.origin;

// --- Utility: UUID v4 ---
function uuid4() {
  return ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
    (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
  );
}

// --- Utility: format bytes ---
function fmtBytes(n) {
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1024 / 1024).toFixed(1) + ' MB';
}

// --- Utility: format ISO date ---
function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString('es-AR', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' });
}

// ============================================================
// Health bar component
// ============================================================
document.addEventListener('alpine:init', () => {

  Alpine.data('healthBar', () => ({
    deps: { redis: null, qdrant: null, ollama: null },
    overall: 'loading',

    async init() {
      await this.refresh();
      setInterval(() => this.refresh(), 30_000);
    },

    async refresh() {
      try {
        const res = await fetch(`${BASE}/health/detail`);
        if (!res.ok) throw new Error(res.statusText);
        const data = await res.json();
        this.deps.redis  = data.redis;
        this.deps.qdrant = data.qdrant;
        this.deps.ollama = data.ollama;
        this.overall     = data.overall;
      } catch (e) {
        this.deps.redis  = { status: 'error', detail: e.message };
        this.deps.qdrant = { status: 'error', detail: e.message };
        this.deps.ollama = { status: 'error', detail: e.message };
        this.overall = 'error';
      }
    },

    dotClass(dep) {
      if (!dep) return 'loading';
      return dep.status === 'ok' ? 'ok' : 'error';
    },
  }));


  // ============================================================
  // Chat panel component
  // ============================================================
  Alpine.data('chatPanel', () => ({
    sessionId: uuid4(),
    messages: [],
    botLogs: [],
    currentStage: 'recepcion',
    input: '',
    loading: false,
    loadingTool: false,
    showTools: true,
    ws: null,

    async send() {
      const text = this.input.trim();
      if (!text || this.loading) return;
      this.input = '';
      this.loading = true;

      this.messages.push({ role: 'user', content: text, ts: new Date() });
      this.$nextTick(() => this.scrollBottom());

      // Create a placeholder for the agent response
      const agentMsgId = this.messages.length;
      this.messages.push({ role: 'agent', content: '', ts: new Date() });

      try {
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${wsProtocol}//${window.location.host}/ws/${this.sessionId}`;
        
        let localWs = new WebSocket(wsUrl);
        
        localWs.onopen = () => {
            localWs.send(text);
        };

        localWs.onmessage = (event) => {
            // Because NDJSON might come in chunks, we process lines
            const lines = event.data.split('\n');
            for (let line of lines) {
                if (!line.trim()) continue;
                try {
                    const data = JSON.parse(line);
                    if (data.type === 'chunk') {
                        this.messages[agentMsgId].content += data.content;
                        this.loading = false;
                        this.$nextTick(() => this.scrollBottom());
                    } else if (data.type === 'tool_call_chunk' || data.type === 'tool_start') {
                        this.loadingTool = true;
                        // Avoid adding duplicates if tool_call_chunk arrives multiple times for same tool
                        // We will rely on tool_end to populate the log definitively
                    } else if (data.type === 'tool_end') {
                        this.loadingTool = false;
                        if (data.tool_name === 'marcar_etapa_conversacion') {
                            // Extract the args roughly
                            const match = data.result.match(/Etapa de conversación actualizada a: (.*)/);
                            if (match) this.currentStage = match[1];
                        }
                        this.botLogs.push({
                            tool_name: data.tool_name,
                            args: '...', // We don't have exact args from tool_end unless we intercept them in backend, but we can just say "ver result"
                            result: data.result
                        });
                        this.$nextTick(() => this.scrollBottom());
                    }
                } catch (e) {
                    console.error('JSON Parse error', e, line);
                }
            }
        };

        localWs.onclose = () => {
            this.loading = false;
            this.loadingTool = false;
        };

        localWs.onerror = (e) => {
             console.error('WebSocket error', e);
             this.loading = false;
        };

      } catch (e) {
        this.messages[agentMsgId].content = `Error: ${e.message}`;
        this.loading = false;
      }
    },

    newSession() {
      this.sessionId = uuid4();
      this.messages = [];
      this.botLogs = [];
      this.currentStage = 'recepcion';
      this.loadingTool = false;
    },

    fmtTime(d) {
      return d instanceof Date
        ? d.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
        : '';
    },

    scrollBottom() {
      const el = this.$refs.messages;
      if (el) el.scrollTop = el.scrollHeight;
    },

    onKeydown(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.send();
      }
    },

    fmtToolArgs(args) {
      try { return JSON.stringify(args, null, 2); }
      catch { return String(args); }
    },

    fmtToolResult(result) {
      if (typeof result === 'string') {
        try { return JSON.stringify(JSON.parse(result), null, 2); }
        catch { return result; }
      }
      try { return JSON.stringify(result, null, 2); }
      catch { return String(result); }
    },
  }));


  // ============================================================
  // Knowledge manager component
  // ============================================================
  Alpine.data('knowledgePanel', () => ({
    files: [],
    selected: null,       // { name, content }
    editContent: '',
    isEditing: false,
    loadingFile: false,
    savingFile: false,
    deletingFile: null,
    reindex: null,        // { jobId, status, chunks, error }
    reindexPollTimer: null,
    uploadName: '',

    async init() {
      await this.loadFiles();
    },

    async loadFiles() {
      try {
        const res = await fetch(`${BASE}/knowledge`);
        this.files = await res.json();
      } catch (e) {
        console.error('loadFiles:', e);
      }
    },

    async viewFile(file) {
      if (this.savingFile) return;
      this.isEditing = false;
      this.loadingFile = true;
      this.selected = { name: file.name, content: '' };
      try {
        const res = await fetch(`${BASE}/knowledge/${encodeURIComponent(file.name)}`);
        const data = await res.json();
        this.selected = data;
        this.editContent = data.content;
      } catch (e) {
        console.error('viewFile:', e);
      } finally {
        this.loadingFile = false;
      }
    },

    startEdit() {
      if (!this.selected) return;
      this.editContent = this.selected.content;
      this.isEditing = true;
    },

    async saveFile() {
      if (!this.selected || this.savingFile) return;
      this.savingFile = true;
      try {
        const res = await fetch(`${BASE}/knowledge/${encodeURIComponent(this.selected.name)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: this.editContent }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        this.selected.content = this.editContent;
        this.isEditing = false;
        await this.loadFiles();
      } catch (e) {
        alert(`Error al guardar: ${e.message}`);
      } finally {
        this.savingFile = false;
      }
    },

    cancelEdit() {
      this.editContent = this.selected?.content || '';
      this.isEditing = false;
    },

    async deleteFile(name) {
      if (!confirm(`¿Borrar "${name}"?`)) return;
      this.deletingFile = name;
      try {
        await fetch(`${BASE}/knowledge/${encodeURIComponent(name)}`, { method: 'DELETE' });
        if (this.selected?.name === name) this.selected = null;
        await this.loadFiles();
      } catch (e) {
        alert(`Error al borrar: ${e.message}`);
      } finally {
        this.deletingFile = null;
      }
    },

    async uploadFile(event) {
      const file = event.target.files[0];
      if (!file) return;
      const form = new FormData();
      form.append('file', file);
      try {
        const res = await fetch(`${BASE}/knowledge`, { method: 'POST', body: form });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || res.statusText);
        }
        await this.loadFiles();
        event.target.value = '';
      } catch (e) {
        alert(`Error al subir: ${e.message}`);
      }
    },

    async triggerReindex() {
      if (this.reindex?.status === 'running' || this.reindex?.status === 'pending') return;
      try {
        const res = await fetch(`${BASE}/knowledge/reindex`, { method: 'POST' });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || res.statusText);
        }
        const data = await res.json();
        this.reindex = { jobId: data.job_id, status: data.status, chunks: null, error: null };
        this.startPolling();
      } catch (e) {
        alert(`Error al re-indexar: ${e.message}`);
      }
    },

    startPolling() {
      if (this.reindexPollTimer) clearInterval(this.reindexPollTimer);
      this.reindexPollTimer = setInterval(async () => {
        if (!this.reindex?.jobId) { clearInterval(this.reindexPollTimer); return; }
        try {
          const res = await fetch(`${BASE}/knowledge/reindex/${this.reindex.jobId}`);
          const data = await res.json();
          this.reindex.status = data.status;
          this.reindex.chunks = data.chunks_indexed;
          this.reindex.error  = data.error_detail;
          if (data.status === 'done' || data.status === 'error') {
            clearInterval(this.reindexPollTimer);
          }
        } catch { clearInterval(this.reindexPollTimer); }
      }, 2000);
    },

    reindexLabel() {
      if (!this.reindex) return 'Re-indexar';
      switch (this.reindex.status) {
        case 'pending': return 'Iniciando…';
        case 'running': return 'Indexando…';
        case 'done':    return `✓ ${this.reindex.chunks} chunks`;
        case 'error':   return '✗ Error';
        default:        return 'Re-indexar';
      }
    },

    get reindexRunning() {
      return this.reindex?.status === 'pending' || this.reindex?.status === 'running';
    },

    renderedContent() {
      if (!this.selected?.content) return '';
      return marked.parse(this.selected.content);
    },

    fmtBytes,
    fmtDate,
  }));

});
