// Searchable combobox for the dependent "country -> city" fields (vanilla JS, no dependencies).
//
// Progressive enhancement: the original <select> stays in the form as the source of the submitted value;
// without JavaScript the plain select is simply shown. Markup contract (set by the Django forms):
//   <select data-combobox="local">                                  options are filtered in the browser
//   <select data-combobox="remote" data-remote-url=".../api/cities/"  options come from the server search
//           data-depends-on="id_country" data-limit="50">             and are reloaded when that select changes
// Optional texts (already translated on the server): data-placeholder, data-empty-text, data-loading-text,
// data-clear-label, data-disabled-placeholder.
(function () {
    'use strict';

    // Same normalization as mainapp.geo_utils.normalize_search on the server: no case, accents or apostrophes.
    function normalize(text) {
        return String(text || '')
            .normalize('NFKD')
            .replace(/[̀-ͯ]/g, '')
            .replace(/[`'’‘ʻʼ]/g, '')
            .toLowerCase();
    }

    function debounce(fn, delay) {
        let timer = null;
        return function () {
            const args = arguments;
            clearTimeout(timer);
            timer = setTimeout(function () { fn.apply(null, args); }, delay);
        };
    }

    function Combobox(select) {
        this.select = select;
        this.remote = select.dataset.combobox === 'remote';
        this.limit = parseInt(select.dataset.limit, 10) || 50;
        this.emptyText = select.dataset.emptyText || 'Nothing found';
        this.loadingText = select.dataset.loadingText || 'Loading…';
        this.clearLabel = select.dataset.clearLabel || 'Clear';
        this.items = [];          // [{value, label}] currently shown
        this.activeIndex = -1;
        this.open = false;
        this.loading = false;
        this.requestId = 0;
        this.cache = new Map();
        this.dependsOn = select.dataset.dependsOn ? document.getElementById(select.dataset.dependsOn) : null;

        const emptyOption = select.querySelector('option[value=""]');
        this.placeholder = select.dataset.placeholder || (emptyOption ? emptyOption.textContent : '');
        this.disabledPlaceholder = select.dataset.disabledPlaceholder || this.placeholder;

        if (!this.remote) {
            this.allItems = Array.prototype.filter.call(select.options, function (option) {
                return option.value !== '';
            }).map(function (option) {
                return { value: option.value, label: option.textContent.trim(), search: option.dataset.search || '' };
            });
        }

        this.build();
        this.syncFromSelect();
        this.bind();
        this.updateDisabled();
    }

    Combobox.prototype.build = function () {
        const select = this.select;
        const uid = (select.id || select.name || 'combobox') + '-combobox';

        this.root = document.createElement('div');
        this.root.className = 'combobox';

        this.input = document.createElement('input');
        this.input.type = 'text';
        this.input.id = uid;
        this.input.className = 'combobox-input';
        this.input.setAttribute('role', 'combobox');
        this.input.setAttribute('aria-autocomplete', 'list');
        this.input.setAttribute('aria-expanded', 'false');
        this.input.setAttribute('aria-controls', uid + '-list');
        this.input.setAttribute('aria-haspopup', 'listbox');
        this.input.autocomplete = 'off';
        this.input.setAttribute('autocapitalize', 'off');
        this.input.spellcheck = false;
        this.input.setAttribute('enterkeyhint', 'search');

        this.clearButton = document.createElement('button');
        this.clearButton.type = 'button';
        this.clearButton.className = 'combobox-clear';
        this.clearButton.setAttribute('aria-label', this.clearLabel);
        this.clearButton.tabIndex = -1;
        this.clearButton.hidden = true;
        this.clearButton.textContent = '×';

        this.list = document.createElement('ul');
        this.list.id = uid + '-list';
        this.list.className = 'combobox-list';
        this.list.setAttribute('role', 'listbox');
        this.list.hidden = true;

        this.root.appendChild(this.input);
        this.root.appendChild(this.clearButton);
        this.root.appendChild(this.list);
        select.parentNode.insertBefore(this.root, select);
        select.classList.add('combobox-native');
        select.hidden = true;
        select.setAttribute('aria-hidden', 'true');
        select.tabIndex = -1;

        // Existing <label for="select-id"> now points at the visible input.
        if (select.id) {
            document.querySelectorAll('label[for="' + select.id + '"]').forEach(function (label) {
                label.setAttribute('for', uid);
            });
        }
    };

    Combobox.prototype.selectedOption = function () {
        const option = this.select.options[this.select.selectedIndex];
        return option && option.value !== '' ? option : null;
    };

    Combobox.prototype.syncFromSelect = function () {
        const option = this.selectedOption();
        this.selectedValue = option ? option.value : '';
        this.selectedLabel = option ? option.textContent.trim() : '';
        this.input.value = this.selectedLabel;
        this.clearButton.hidden = !this.selectedValue;
    };

    Combobox.prototype.updateDisabled = function () {
        const blocked = Boolean(this.dependsOn && !this.dependsOn.value);
        this.input.disabled = blocked;
        this.input.placeholder = blocked ? this.disabledPlaceholder : this.placeholder;
        this.root.classList.toggle('combobox-disabled', blocked);
        if (blocked) {
            this.clearButton.hidden = true;
        }
    };

    Combobox.prototype.bind = function () {
        const self = this;

        this.input.addEventListener('focus', function () {
            self.input.select();
            self.search('');
        });
        this.input.addEventListener('click', function () {
            if (!self.open) {
                self.search('');
            }
        });
        this.input.addEventListener('input', function () {
            self.search(self.input.value);
        });
        this.input.addEventListener('keydown', function (event) { self.onKeydown(event); });
        this.input.addEventListener('blur', function () {
            self.close();
            self.input.value = self.selectedLabel; // typed text that was not chosen is discarded
        });

        this.list.addEventListener('mousedown', function (event) {
            event.preventDefault(); // keep the focus in the input so blur does not close the list first
        });
        this.list.addEventListener('click', function (event) {
            const li = event.target.closest('li[data-index]');
            if (li) {
                self.choose(self.items[Number(li.dataset.index)]);
            }
        });
        this.list.addEventListener('mousemove', function (event) {
            const li = event.target.closest('li[data-index]');
            if (li && Number(li.dataset.index) !== self.activeIndex) {
                self.setActive(Number(li.dataset.index), false);
            }
        });

        this.clearButton.addEventListener('mousedown', function (event) { event.preventDefault(); });
        this.clearButton.addEventListener('click', function () {
            self.choose(null);
            self.input.focus();
        });

        if (this.remote) {
            this.remoteSearch = debounce(function (query) { self.fetchCities(query); }, 250);
        }
        if (this.dependsOn) {
            this.dependsOn.addEventListener('change', function () {
                self.cache.clear();
                self.setOptionsOnly(null); // the old city never belongs to the new country
                self.syncFromSelect();
                self.updateDisabled();
                self.close();
            });
        }
        // Reset (e.g. "Clear filters" is a link, but forms may reset): re-read the select.
        const form = this.select.form;
        if (form) {
            form.addEventListener('reset', function () {
                setTimeout(function () { self.syncFromSelect(); self.updateDisabled(); }, 0);
            });
        }
    };

    Combobox.prototype.onKeydown = function (event) {
        switch (event.key) {
            case 'ArrowDown':
                event.preventDefault();
                if (!this.open) {
                    this.search(this.input.value === this.selectedLabel ? '' : this.input.value);
                } else {
                    this.setActive(Math.min(this.items.length - 1, this.activeIndex + 1), true);
                }
                break;
            case 'ArrowUp':
                event.preventDefault();
                if (this.open) {
                    this.setActive(Math.max(0, this.activeIndex - 1), true);
                }
                break;
            case 'Enter':
                if (this.open) {
                    event.preventDefault(); // do not submit the form while picking
                    if (this.items[this.activeIndex]) {
                        this.choose(this.items[this.activeIndex]);
                    }
                }
                break;
            case 'Escape':
                if (this.open) {
                    event.preventDefault();
                    this.close();
                    this.input.value = this.selectedLabel;
                }
                break;
            case 'Tab':
                this.close();
                break;
            default:
        }
    };

    // The text equal to the chosen label means "show everything", otherwise it is a real query.
    Combobox.prototype.search = function (rawQuery) {
        if (this.input.disabled) {
            return;
        }
        const query = rawQuery === this.selectedLabel ? '' : rawQuery;
        if (this.remote) {
            this.openList();
            const key = this.cacheKey(query);
            if (this.cache.has(key)) {
                this.renderItems(this.cache.get(key), query);
            } else {
                this.showMessage(this.loadingText);
                this.remoteSearch(query);
            }
            return;
        }
        const needle = normalize(query).trim();
        let matches = this.allItems;
        if (needle) {
            const starts = [];
            const contains = [];
            this.allItems.forEach(function (item) {
                // The label (with the flag) wins; data-search holds the names in the other languages + ISO code.
                const position = normalize(item.label).replace(/^[^\p{L}\p{N}]+/u, '').indexOf(needle);
                if (position === 0) {
                    starts.push(item);
                } else if (position > 0 || normalize(item.search).indexOf(needle) >= 0) {
                    contains.push(item);
                }
            });
            matches = starts.concat(contains);
        }
        this.openList();
        this.renderItems(matches, query);
    };

    Combobox.prototype.cacheKey = function (query) {
        return (this.dependsOn ? this.dependsOn.value : '') + '|' + normalize(query).trim();
    };

    Combobox.prototype.fetchCities = function (query) {
        const self = this;
        const countryId = this.dependsOn ? this.dependsOn.value : '';
        if (!countryId) {
            return;
        }
        const requestId = ++this.requestId;
        const url = new URL(this.select.dataset.remoteUrl, window.location.origin);
        url.searchParams.set('country', countryId);
        url.searchParams.set('limit', String(this.limit));
        if (query.trim()) {
            url.searchParams.set('q', query.trim());
        }
        fetch(url, { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error('HTTP ' + response.status);
                }
                return response.json();
            })
            .then(function (cities) {
                if (requestId !== self.requestId) {
                    return; // a newer request superseded this one
                }
                const items = cities.map(function (city) {
                    return { value: String(city.id), label: city.name };
                });
                self.cache.set(self.cacheKey(query), items);
                if (self.open) {
                    self.renderItems(items, query);
                }
            })
            .catch(function () {
                if (requestId === self.requestId && self.open) {
                    self.showMessage(self.emptyText);
                }
            });
    };

    Combobox.prototype.openList = function () {
        this.open = true;
        this.list.hidden = false;
        this.input.setAttribute('aria-expanded', 'true');
    };

    Combobox.prototype.close = function () {
        this.open = false;
        this.list.hidden = true;
        this.activeIndex = -1;
        this.input.setAttribute('aria-expanded', 'false');
        this.input.removeAttribute('aria-activedescendant');
    };

    Combobox.prototype.showMessage = function (text) {
        this.items = [];
        this.activeIndex = -1;
        this.list.textContent = '';
        const li = document.createElement('li');
        li.className = 'combobox-message';
        li.setAttribute('role', 'presentation');
        li.textContent = text;
        this.list.appendChild(li);
    };

    Combobox.prototype.renderItems = function (items, query) {
        this.items = items;
        if (!items.length) {
            this.showMessage(this.emptyText);
            return;
        }
        const needle = normalize(query).trim();
        this.list.textContent = '';
        const fragment = document.createDocumentFragment();
        const self = this;
        items.forEach(function (item, index) {
            const li = document.createElement('li');
            li.id = self.list.id + '-' + index;
            li.className = 'combobox-option';
            li.dataset.index = String(index);
            li.setAttribute('role', 'option');
            li.setAttribute('aria-selected', String(item.value === self.selectedValue));
            self.highlight(li, item.label, needle);
            fragment.appendChild(li);
        });
        this.list.appendChild(fragment);
        // Start on the chosen item (when the whole list is shown), otherwise on the best match.
        const selectedIndex = items.findIndex(function (item) { return item.value === self.selectedValue; });
        this.setActive(!needle && selectedIndex >= 0 ? selectedIndex : 0, true);
    };

    // Builds text + <mark> nodes (never innerHTML: city names are data, not markup).
    Combobox.prototype.highlight = function (element, label, needle) {
        if (needle) {
            // Walk the label, remembering which original characters survive normalization.
            let normalized = '';
            const map = [];
            Array.prototype.forEach.call(label, function (char, index) {
                const piece = normalize(char);
                for (let i = 0; i < piece.length; i += 1) {
                    normalized += piece[i];
                    map.push(index);
                }
            });
            const position = normalized.indexOf(needle);
            if (position >= 0) {
                const start = map[position];
                const end = map[position + needle.length - 1] + 1;
                element.appendChild(document.createTextNode(label.slice(0, start)));
                const mark = document.createElement('mark');
                mark.textContent = label.slice(start, end);
                element.appendChild(mark);
                element.appendChild(document.createTextNode(label.slice(end)));
                return;
            }
        }
        element.textContent = label;
    };

    Combobox.prototype.setActive = function (index, scroll) {
        const options = this.list.querySelectorAll('li[data-index]');
        if (!options.length) {
            return;
        }
        if (this.activeIndex >= 0 && options[this.activeIndex]) {
            options[this.activeIndex].classList.remove('is-active');
        }
        this.activeIndex = index;
        const active = options[index];
        if (active) {
            active.classList.add('is-active');
            this.input.setAttribute('aria-activedescendant', active.id);
            if (scroll) {
                const top = active.offsetTop;
                const bottom = top + active.offsetHeight;
                if (top < this.list.scrollTop) {
                    this.list.scrollTop = top;
                } else if (bottom > this.list.scrollTop + this.list.clientHeight) {
                    this.list.scrollTop = bottom - this.list.clientHeight;
                }
            }
        }
    };

    // Replace the options of the native select by "empty (+ one chosen)" so it stays the source of the value.
    Combobox.prototype.setOptionsOnly = function (item) {
        if (!this.remote && item) {
            this.select.value = item.value;
            return;
        }
        if (!this.remote) {
            this.select.value = '';
            return;
        }
        this.select.textContent = '';
        const empty = document.createElement('option');
        empty.value = '';
        empty.textContent = this.placeholder;
        this.select.appendChild(empty);
        if (item) {
            const option = document.createElement('option');
            option.value = item.value;
            option.textContent = item.label;
            option.selected = true;
            this.select.appendChild(option);
        }
    };

    Combobox.prototype.choose = function (item) {
        const changed = (item ? item.value : '') !== this.selectedValue;
        this.setOptionsOnly(item);
        this.syncFromSelect();
        this.close();
        if (changed) {
            this.select.dispatchEvent(new Event('change', { bubbles: true }));
        }
    };

    function init() {
        // Country (local) first so that the dependent city combobox sees its final state.
        ['local', 'remote'].forEach(function (mode) {
            document.querySelectorAll('select[data-combobox="' + mode + '"]').forEach(function (select) {
                if (!select.dataset.comboboxReady) {
                    select.dataset.comboboxReady = '1';
                    new Combobox(select);
                }
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
