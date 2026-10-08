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

    const switcher = document.createElement('div');
    switcher.className = 'theme-switcher';
    switcher.innerHTML = `
        <button class="theme-toggle" type="button" role="switch" aria-label="${t.themeLabel}">
            <span class="theme-toggle-thumb" aria-hidden="true">
                <svg class="theme-icon theme-icon-sun" viewBox="0 0 24 24" focusable="false">
                    <circle cx="12" cy="12" r="4"></circle>
                    <path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"></path>
                </svg>
                <svg class="theme-icon theme-icon-moon" viewBox="0 0 24 24" focusable="false">
                    <path d="M20.2 15.4A8.5 8.5 0 0 1 8.6 3.8 8.6 8.6 0 1 0 20.2 15.4Z"></path>
                    <circle cx="17.5" cy="6.5" r=".8"></circle>
                </svg>
            </span>
        </button>
    `;

    const toggle = switcher.querySelector('.theme-toggle');
    const updateToggle = () => {
        const isDark = body.classList.contains('dark-theme');
        toggle.setAttribute('aria-checked', isDark ? 'true' : 'false');
        toggle.title = `${t.switchLabel}: ${isDark ? t.dark : t.light}`;
    };

    toggle.addEventListener('click', () => {
        const isDark = !body.classList.contains('dark-theme');
        body.classList.toggle('dark-theme', isDark);
        window.localStorage.setItem(storageKey, isDark ? 'dark' : 'light');
        updateToggle();
    });

    const target = document.querySelector('.nav-actions') || document.querySelector('.create-toolbar') || body;
    target.appendChild(switcher);
    updateToggle();
}());