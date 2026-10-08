(function () {
    const storageKey = 'careerup-theme';
    const savedTheme = window.localStorage.getItem(storageKey);
    const body = document.body;
    const language = (document.documentElement.lang || 'en').toLowerCase().split(/[-_]/)[0];
    const translations = {
        en: {
            switchLabel: 'Change view',
            themeLabel: 'Theme selection',
            light: 'Light',
            dark: 'Dark',
        },
        ru: {
            switchLabel: 'Сменить вид',
            themeLabel: 'Выбор темы',
            light: 'Светлая',
            dark: 'Тёмная',
        },
        uz: {
            switchLabel: "Ko'rinishni o'zgartirish",
            themeLabel: 'Mavzu tanlovi',
            light: 'Yorqin',
            dark: 'Qorong\'i',
        },
        uzb: {
            switchLabel: "Ko'rinishni o'zgartirish",
            themeLabel: 'Mavzu tanlovi',
            light: 'Yorqin',
            dark: 'Qorong\'i',
        },
    };
    const normalizedLanguage = language === 'uzb' ? 'uz' : language;
    const t = translations[normalizedLanguage] || translations.en;

    if (savedTheme === 'dark') {
        body.classList.add('dark-theme');
    }

    if (body.dataset.themeSwitcher === 'off') {
        return;
    }

    const switcher = document.createElement('details');
    switcher.className = 'theme-switcher';
    switcher.innerHTML = `
        <summary class="theme-toggle">◐ <span>${t.switchLabel}</span></summary>
        <div class="theme-options" role="group" aria-label="${t.themeLabel}">
            <button type="button" data-theme-option="light">☀ <span>${t.light}</span></button>
            <button type="button" data-theme-option="dark">☾ <span>${t.dark}</span></button>
        </div>
    `;

    const updateOptions = () => {
        const isDark = body.classList.contains('dark-theme');
        switcher.querySelectorAll('[data-theme-option]').forEach((option) => {
            option.classList.toggle('active', option.dataset.themeOption === (isDark ? 'dark' : 'light'));
            option.setAttribute('aria-pressed', option.dataset.themeOption === (isDark ? 'dark' : 'light') ? 'true' : 'false');
        });
    };

    switcher.querySelectorAll('[data-theme-option]').forEach((option) => {
        option.addEventListener('click', () => {
            const isDark = option.dataset.themeOption === 'dark';
            body.classList.toggle('dark-theme', isDark);
            window.localStorage.setItem(storageKey, isDark ? 'dark' : 'light');
            updateOptions();
            switcher.removeAttribute('open');
        });
    });

    const target = document.querySelector('.nav-actions') || document.querySelector('.create-toolbar') || body;
    target.appendChild(switcher);
    updateOptions();
}());