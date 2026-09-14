(function () {
    const storageKey = 'careerup-theme';
    const savedTheme = window.localStorage.getItem(storageKey);
    const body = document.body;

    if (savedTheme === 'dark') {
        body.classList.add('dark-theme');
    }

    const switcher = document.createElement('details');
    switcher.className = 'theme-switcher';
    switcher.innerHTML = `
        <summary class="theme-toggle">◐ <span>Сменить вид</span></summary>
        <div class="theme-options" role="group" aria-label="Выбор темы">
            <button type="button" data-theme-option="light">☀ <span>Светлая</span></button>
            <button type="button" data-theme-option="dark">☾ <span>Тёмная</span></button>
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