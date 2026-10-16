/* Header unread badge, updated live over /ws/notifications/.
   Also re-dispatches "new_message" pushes as a DOM event for the inbox page. */
(function () {
    'use strict';

    var badges = document.querySelectorAll('[data-chat-unread-badge]');
    if (!badges.length || !('WebSocket' in window)) {
        return;
    }

    var socket = null;
    var retries = 0;
    var timer = null;

    function setUnread(count) {
        var n = parseInt(count, 10) || 0;
        badges.forEach(function (badge) {
            badge.textContent = n > 99 ? '99+' : String(n);
            badge.hidden = n <= 0;
        });
    }

    function handle(data) {
        if (data.type === 'unread') {
            setUnread(data.unread);
        } else if (data.type === 'new_message') {
            setUnread(data.unread);
            document.dispatchEvent(new CustomEvent('chat:new-message', { detail: data }));
        }
    }

    function connect() {
        var scheme = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
        socket = new WebSocket(scheme + window.location.host + '/ws/notifications/');
        socket.onopen = function () {
            retries = 0;
        };
        socket.onmessage = function (event) {
            try {
                handle(JSON.parse(event.data));
            } catch (error) {
                /* ignore malformed frames */
            }
        };
        socket.onclose = function () {
            // Exponential backoff with jitter, capped at 30 s.
            var delay = Math.min(30000, 1000 * Math.pow(2, retries)) + Math.random() * 500;
            retries += 1;
            window.clearTimeout(timer);
            timer = window.setTimeout(connect, delay);
        };
    }

    connect();
}());
