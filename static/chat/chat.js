/* Conversation page: live chat over /ws/chat/<id>/ with HTTP fallback and auto-reconnect.
   Message text and file names are only ever inserted with textContent (never innerHTML). */
(function () {
    'use strict';

    var configElement = document.getElementById('chat-config');
    var log = document.getElementById('chat-log');
    if (!configElement || !log) {
        return;
    }

    var cfg = JSON.parse(configElement.textContent);
    var t = cfg.i18n;
    var form = document.getElementById('chat-form');
    var textarea = document.getElementById('chat-text');
    var fileInput = document.getElementById('chat-file');
    var fileNameLabel = document.getElementById('chat-file-name');
    var errorBox = document.getElementById('chat-error');
    var statusBox = document.getElementById('chat-status');
    var csrfInput = form ? form.querySelector('input[name="csrfmiddlewaretoken"]') : null;
    var canSend = cfg.canSend;

    var socket = null;
    var retries = 0;
    var reconnectTimer = null;
    var hadConnection = false;
    var lastText = '';

    // ------------------------------------------------------------------ helpers

    function setStatus(state, label) {
        if (!statusBox) { return; }
        statusBox.dataset.state = state;
        statusBox.textContent = label;
    }

    // WebSocket errors carry only a code (the socket has no request language), so the page's own
    // translations win; errors from HTTP responses and client-side checks come already localised.
    function showError(code, detail, preferDetail) {
        if (!errorBox) { return; }
        var byCode = t.errors && t.errors[code];
        var text = (preferDetail ? (detail || byCode) : (byCode || detail)) || t.send_failed;
        errorBox.textContent = text;
        errorBox.hidden = false;
    }

    function clearError() {
        if (errorBox) {
            errorBox.hidden = true;
            errorBox.textContent = '';
        }
    }

    function formatTime(iso) {
        var date = new Date(iso);
        if (isNaN(date.getTime())) { return ''; }
        return date.toLocaleString([], { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
    }

    function formatSize(bytes) {
        if (bytes < 1024) { return bytes + ' B'; }
        if (bytes < 1024 * 1024) { return (bytes / 1024).toFixed(1) + ' KB'; }
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    function safeUrl(url) {
        // Only same-site relative URLs coming from the server are used as link targets.
        return typeof url === 'string' && url.charAt(0) === '/' && url.charAt(1) !== '/' ? url : '#';
    }

    function scrollToBottom() {
        log.scrollTop = log.scrollHeight;
    }

    function isNearBottom() {
        return log.scrollHeight - log.scrollTop - log.clientHeight < 120;
    }

    // Local time for the server-rendered messages.
    log.querySelectorAll('time[datetime]').forEach(function (el) {
        var formatted = formatTime(el.getAttribute('datetime'));
        if (formatted) { el.textContent = formatted; }
    });

    // ------------------------------------------------------------------ rendering

    function renderMessage(m) {
        var mine = m.sender_id === cfg.userId;
        var row = document.createElement('div');
        row.className = 'chat-message' + (mine ? ' chat-message--mine' : '');
        row.dataset.messageId = String(m.id);
        row.dataset.senderId = String(m.sender_id);
        if (!mine && !m.read_at) { row.dataset.unread = '1'; }

        var bubble = document.createElement('div');
        bubble.className = 'chat-bubble';
        if (m.text) {
            var text = document.createElement('div');
            text.className = 'chat-text';
            text.textContent = m.text;
            bubble.appendChild(text);
        }
        if (m.attachment) {
            var url = safeUrl(m.attachment.url);
            if (m.attachment.is_image) {
                var imageLink = document.createElement('a');
                imageLink.href = url;
                imageLink.target = '_blank';
                imageLink.rel = 'noopener';
                var image = document.createElement('img');
                image.className = 'chat-image';
                image.src = url;
                image.alt = m.attachment.name;
                image.loading = 'lazy';
                imageLink.appendChild(image);
                bubble.appendChild(imageLink);
            }
            var link = document.createElement('a');
            link.className = 'chat-attachment';
            link.href = url;
            link.target = '_blank';
            link.rel = 'noopener';
            link.textContent = m.attachment.name + ' (' + formatSize(m.attachment.size) + ')';
            bubble.appendChild(link);
        }
        row.appendChild(bubble);

        var meta = document.createElement('div');
        meta.className = 'chat-meta';
        var time = document.createElement('time');
        time.setAttribute('datetime', m.created_at);
        time.textContent = formatTime(m.created_at);
        meta.appendChild(time);
        if (mine) {
            var mark = document.createElement('span');
            mark.className = 'chat-read-mark';
            mark.dataset.read = m.read_at ? '1' : '0';
            mark.textContent = m.read_at ? '✓✓ ' + t.read : '✓';
            meta.appendChild(mark);
        } else {
            var report = document.createElement('button');
            report.type = 'button';
            report.className = 'chat-report-btn';
            report.dataset.reportId = String(m.id);
            report.textContent = t.report;
            meta.appendChild(report);
        }
        row.appendChild(meta);
        return row;
    }

    function appendMessage(m) {
        if (log.querySelector('[data-message-id="' + String(m.id) + '"]')) {
            return; // already shown (HTTP response and WebSocket echo both deliver it)
        }
        var empty = log.querySelector('[data-chat-empty]');
        if (empty) { empty.remove(); }
        var stick = isNearBottom() || m.sender_id === cfg.userId;
        log.appendChild(renderMessage(m));
        if (stick) { scrollToBottom(); }
        if (m.sender_id !== cfg.userId) { requestRead(); }
    }

    function markRead(ids) {
        ids.forEach(function (id) {
            var mark = log.querySelector('[data-message-id="' + String(id) + '"] .chat-read-mark');
            if (mark) {
                mark.dataset.read = '1';
                mark.textContent = '✓✓ ' + t.read;
            }
        });
    }

    // ------------------------------------------------------------------ read receipts

    function requestRead() {
        if (document.hidden) { return; }
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'read' }));
        }
    }

    document.addEventListener('visibilitychange', requestRead);

    // ------------------------------------------------------------------ catching up after a reconnect

    function normalizeApiMessage(m) {
        return {
            id: m.id,
            sender_id: m.sender.id,
            text: m.text,
            attachment: m.attachment,
            created_at: m.created_at,
            read_at: m.read_at,
        };
    }

    function catchUp() {
        // Messages that arrived while the socket was down: fetch the latest page over the session-authenticated API.
        fetch('/api/conversations/' + cfg.conversationId + '/messages/?page_size=50', {
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' },
        }).then(function (response) {
            return response.ok ? response.json() : null;
        }).then(function (data) {
            if (!data || !data.results) { return; }
            data.results.slice().reverse().forEach(function (m) { appendMessage(normalizeApiMessage(m)); });
        }).catch(function () { /* best effort */ });
    }

    // ------------------------------------------------------------------ WebSocket

    function disableComposer() {
        canSend = false;
        if (form) {
            Array.prototype.forEach.call(form.elements, function (el) { el.disabled = true; });
        }
        showError('blocked', t.blockedNotice);
    }

    function onSocketMessage(event) {
        var data;
        try {
            data = JSON.parse(event.data);
        } catch (error) {
            return;
        }
        if (data.type === 'ready') {
            setStatus('online', t.connected);
            if (!data.can_send && canSend) { disableComposer(); }
            if (hadConnection) { catchUp(); }
            hadConnection = true;
            requestRead();
        } else if (data.type === 'message') {
            appendMessage(data.message);
        } else if (data.type === 'read') {
            if (data.reader_id !== cfg.userId) { markRead(data.message_ids); }
        } else if (data.type === 'error') {
            if (data.code === 'blocked') {
                disableComposer();
            } else {
                if (textarea && !textarea.value && lastText) { textarea.value = lastText; }
                showError(data.code, data.detail);
            }
        }
    }

    function connect() {
        if (!('WebSocket' in window)) {
            setStatus('offline', t.reconnecting);
            return;
        }
        var scheme = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
        setStatus('offline', retries ? t.reconnecting : t.connecting);
        socket = new WebSocket(scheme + window.location.host + cfg.wsPath);
        socket.onopen = function () { retries = 0; };
        socket.onmessage = onSocketMessage;
        socket.onclose = function () {
            setStatus('offline', t.reconnecting);
            var delay = Math.min(30000, 1000 * Math.pow(2, retries)) + Math.random() * 500;
            retries += 1;
            window.clearTimeout(reconnectTimer);
            reconnectTimer = window.setTimeout(connect, delay);
        };
    }

    // ------------------------------------------------------------------ sending

    function postHttp(formData) {
        var headers = { 'X-Requested-With': 'XMLHttpRequest' };
        if (csrfInput) { headers['X-CSRFToken'] = csrfInput.value; }
        return fetch(cfg.sendUrl, {
            method: 'POST',
            body: formData,
            credentials: 'same-origin',
            headers: headers,
        }).then(function (response) {
            return response.json().then(function (data) {
                return { ok: response.ok, data: data };
            });
        });
    }

    function extensionOf(name) {
        var index = name.lastIndexOf('.');
        return index < 0 ? '' : name.slice(index + 1).toLowerCase();
    }

    function sendWithHttp(text, file) {
        var formData = new FormData();
        formData.append('text', text);
        if (file) { formData.append('attachment', file); }
        return postHttp(formData).then(function (result) {
            if (result.ok) {
                appendMessage(result.data.message);
                return true;
            }
            if (result.data.error === 'blocked') {
                disableComposer();
            } else {
                showError(result.data.error, result.data.detail, true);
            }
            return false;
        }).catch(function () {
            showError('network', t.send_failed);
            return false;
        });
    }

    function handleSubmit(event) {
        event.preventDefault();
        if (!canSend) { return; }
        clearError();
        var text = textarea.value.trim();
        var file = fileInput && fileInput.files.length ? fileInput.files[0] : null;
        if (!text && !file) { return; }
        if (text.length > cfg.maxLength) { showError('too_long'); return; }

        if (file) {
            if (file.size > cfg.maxBytes) { showError('bad_attachment', t.fileTooLarge, true); return; }
            if (cfg.allowedExtensions.indexOf(extensionOf(file.name)) < 0) {
                showError('bad_attachment', t.fileTypeNotAllowed, true);
                return;
            }
            sendWithHttp(text, file).then(function (ok) {
                if (ok) {
                    textarea.value = '';
                    fileInput.value = '';
                    if (fileNameLabel) { fileNameLabel.textContent = ''; }
                }
            });
            return;
        }

        if (socket && socket.readyState === WebSocket.OPEN) {
            lastText = text;
            socket.send(JSON.stringify({ type: 'message', text: text }));
            textarea.value = '';
            autoGrow();
        } else {
            // No live connection: fall back to a plain HTTP request (the server still stores and broadcasts it).
            sendWithHttp(text, null).then(function (ok) {
                if (ok) { textarea.value = ''; autoGrow(); }
            });
        }
    }

    function autoGrow() {
        if (!textarea) { return; }
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 160) + 'px';
    }

    if (form && textarea) {
        form.addEventListener('submit', handleSubmit);
        textarea.addEventListener('input', autoGrow);
        textarea.addEventListener('keydown', function (event) {
            if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
                event.preventDefault();
                form.requestSubmit();
            }
        });
        if (fileInput && fileNameLabel) {
            fileInput.addEventListener('change', function () {
                fileNameLabel.textContent = fileInput.files.length ? fileInput.files[0].name + ' —' : '';
            });
        }
    }

    // ------------------------------------------------------------------ report dialog / confirm

    var dialog = document.getElementById('chat-report-dialog');
    var reportForm = document.getElementById('chat-report-form');
    log.addEventListener('click', function (event) {
        var button = event.target.closest('[data-report-id]');
        if (!button || !dialog || typeof dialog.showModal !== 'function') { return; }
        reportForm.action = cfg.reportUrlTemplate.replace('{id}', button.dataset.reportId);
        reportForm.reset();
        dialog.showModal();
    });
    if (dialog) {
        dialog.querySelectorAll('[data-close-dialog]').forEach(function (el) {
            el.addEventListener('click', function () { dialog.close(); });
        });
    }
    document.querySelectorAll('form[data-confirm]').forEach(function (el) {
        el.addEventListener('submit', function (event) {
            if (!window.confirm(el.dataset.confirm)) { event.preventDefault(); }
        });
    });

    // ------------------------------------------------------------------ start

    scrollToBottom();
    if (canSend) { connect(); } else { setStatus('offline', ''); }
}());
