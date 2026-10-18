// Create / edit listing form: live completeness ring, per-section counters and the section navigation highlight.
(function () {
    'use strict';

    var form = document.querySelector('form.cf');
    if (!form) {
        return;
    }

    var ring = form.querySelector('[data-cf-ring]');
    var percentLabel = form.querySelector('[data-cf-percent]');
    var summary = form.querySelector('[data-cf-summary]');
    var sections = Array.prototype.slice.call(form.querySelectorAll('.cf-section'));
    var tocLinks = Array.prototype.slice.call(document.querySelectorAll('.cf-toc a'));
    var fieldsWord = form.getAttribute('data-fields-word') || '';

    // Only real, user-fillable controls count: the combobox text inputs are nameless, and "clear photo" is a checkbox.
    function controlsOf(root) {
        return Array.prototype.filter.call(root.querySelectorAll('input[name], select[name], textarea[name]'), function (el) {
            return el.type !== 'hidden' && el.type !== 'checkbox' && !el.disabled;
        });
    }

    function isFilled(el) {
        if (el.type === 'file') {
            // On the edit page an existing photo shows up as a link next to the input.
            return el.files.length > 0 || !!(el.closest('.cf-field') && el.closest('.cf-field').querySelector('a[href]'));
        }
        return el.value.trim() !== '';
    }

    function update() {
        var total = 0;
        var done = 0;
        sections.forEach(function (section) {
            var controls = controlsOf(section);
            var filled = controls.filter(isFilled).length;
            var chip = section.querySelector('[data-cf-chip]');
            if (chip) {
                chip.textContent = filled + ' / ' + controls.length;
                chip.classList.toggle('is-done', controls.length > 0 && filled === controls.length);
            }
            total += controls.length;
            done += filled;
        });
        var percent = total ? Math.round(done / total * 100) : 0;
        if (ring) {
            ring.style.setProperty('--cf-progress', percent);
        }
        if (percentLabel) {
            percentLabel.textContent = percent + '%';
        }
        if (summary) {
            summary.textContent = done + ' / ' + total + ' ' + fieldsWord;
        }
    }

    form.addEventListener('input', update);
    form.addEventListener('change', update);
    // The country/city combobox writes to a hidden <select> after a click; wait for it to settle.
    form.addEventListener('click', function () { window.setTimeout(update, 60); });
    window.addEventListener('load', function () { window.setTimeout(update, 120); });
    update();

    // Highlight the section that is currently under the header.
    if ('IntersectionObserver' in window && tocLinks.length) {
        var visible = {};
        var observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                visible[entry.target.id] = entry.isIntersecting;
            });
            var current = sections.filter(function (section) { return visible[section.id]; })[0];
            if (current) {
                tocLinks.forEach(function (link) {
                    link.classList.toggle('is-active', link.getAttribute('href') === '#' + current.id);
                });
            }
        }, { rootMargin: '-25% 0px -55% 0px' });
        sections.forEach(function (section) { observer.observe(section); });
    }

    // After a failed submit, bring the first invalid field into view.
    var firstError = form.querySelector('.cf-field.has-error');
    if (firstError) {
        firstError.scrollIntoView({ block: 'center' });
    }
})();
