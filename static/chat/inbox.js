/* Live updates of the inbox list: reacts to pushes from notifications.js. */
(function () {
    'use strict';

    var root = document.querySelector('[data-chat-inbox]');
    if (!root) {
        return;
    }

    document.addEventListener('chat:new-message', function (event) {
        var data = event.detail;
        var row = root.querySelector('[data-conversation-id="' + String(data.conversation_id) + '"]');
        if (!row) {
            // A conversation that is not on this page yet: simplest correct thing is to reload.
            window.location.reload();
            return;
        }
        var preview = row.querySelector('[data-chat-preview]');
        if (preview) {
            preview.textContent = data.preview || '';
        }
        var badge = row.querySelector('[data-chat-conversation-unread]');
        if (badge) {
            var current = parseInt(badge.textContent, 10) || 0;
            badge.textContent = String(current + 1);
            badge.hidden = false;
        }
        row.classList.add('chat-inbox-item--unread');
        var item = row.closest('li');
        if (item && item.parentNode) {
            item.parentNode.insertBefore(item, item.parentNode.firstChild);
        }
    });
}());
